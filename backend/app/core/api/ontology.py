import os
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import Config
from app.core.managers.prompt_label_manager import PromptLabelManager
from app.core.managers.project_manager import ProjectManager
from app.core.managers.task_manager import TaskManager
from app.core.schemas.project import ProjectStatus
from app.core.schemas.task import TaskStatus
from app.core.service.ontology_generator import OntologyGenerator
from app.core.utils.logger import get_logger
from app.core.utils.text_file_parser import FileParser
from app.core.utils.text_processor import TextProcessor

router = APIRouter()
logger = get_logger("z_graph.api.ontology")

DEFAULT_MINIMUM_NODES = 10
DEFAULT_MINIMUM_EDGES = 10
DEV_APP_ENVS = {"dev", "development", "local"}
SUPPORTED_GRAPH_BACKENDS = {"zep_cloud", "neo4j", "oracle"}


class _LocalFileAdapter:
    """Adapter to save a local staged file into a project."""

    def __init__(self, source_path: str) -> None:
        self._source_path = source_path

    def save(self, destination_path: str) -> None:
        shutil.copyfile(self._source_path, destination_path)


def _error_response(status_code: int, error: str, exc: Exception | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
    }
    if exc is not None:
        payload["traceback"] = traceback.format_exc()
    return JSONResponse(status_code=status_code, content=payload)


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in FileParser.SUPPORTED_EXTENSIONS


def _normalize_minimum_count(value: Any, *, field_name: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be greater than 0")
    return parsed


def _normalize_graph_backend(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_GRAPH_BACKENDS:
        return normalized
    return ""


def _is_graph_backend_configured(graph_backend: str) -> bool:
    if graph_backend == "zep_cloud":
        return bool(Config.ZEP_API_KEY)
    if graph_backend == "neo4j":
        return bool(Config.GRAPHDB_URI and Config.GRAPHDB_USER and Config.GRAPHDB_PASSWORD)
    if graph_backend == "oracle":
        return bool(Config.GRAPHDB_DSN and Config.GRAPHDB_USER and Config.GRAPHDB_PASSWORD)
    return False


def _is_dev_mode() -> bool:
    return str(Config.APP_ENV or "").strip().lower() in DEV_APP_ENVS


def _append_task_latency_event(
    task_manager: TaskManager,
    task_id: str,
    *,
    step: str,
    operation: str,
    elapsed_ms: float,
) -> None:
    if not _is_dev_mode():
        return

    task = task_manager.get_task(task_id)
    if task is None:
        return

    event = {
        "event_id": uuid.uuid4().hex,
        "step": step,
        "operation": operation,
        "elapsed_ms": round(float(elapsed_ms), 2),
        "timestamp": datetime.now().isoformat(),
    }
    progress_detail = dict(task.progress_detail or {})
    latency_events = list(progress_detail.get("latency_events") or [])
    latency_events.append(event)
    if len(latency_events) > 200:
        latency_events = latency_events[-200:]
    progress_detail["latency_events"] = latency_events
    task_manager.update_task(task_id, progress_detail=progress_detail)

    logger.info(
        "task latency [%s] %s - %.2fms",
        step,
        operation,
        elapsed_ms,
    )


def _timed_task_call(
    task_manager: TaskManager,
    task_id: str,
    step: str,
    operation: str,
    func: Callable[..., Any],
    *args,
    **kwargs,
) -> Any:
    started_at = time.perf_counter()
    try:
        return func(*args, **kwargs)
    finally:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        _append_task_latency_event(
            task_manager=task_manager,
            task_id=task_id,
            step=step,
            operation=operation,
            elapsed_ms=elapsed_ms,
        )


@router.post("/ontology/generate")
def generate_ontology(
    files: list[UploadFile] = File(...),
    simulation_requirement: str = Form(...),
    project_name: str = Form("Unnamed Project"),
    additional_context: str = Form(""),
    minimum_nodes: int = Form(DEFAULT_MINIMUM_NODES),
    minimum_edges: int = Form(DEFAULT_MINIMUM_EDGES),
    prompt_label: str = Form("Production"),
    project_id: str = Form(""),
    graph_backend: str = Form(""),
) -> Any:
    try:
        logger.info("----------------Start generating ontology----------------")

        requirement = (simulation_requirement or "").strip()
        if not requirement:
            return _error_response(400, "Please Provide Simulation Requirement")

        uploaded_files = [f for f in files if f and f.filename]
        if not uploaded_files:
            return _error_response(400, "Upload at least one document file")

        normalized_project_id = str(project_id or "").strip()
        normalized_project_name = str(project_name or "").strip() or "Unnamed Project"
        normalized_graph_backend = _normalize_graph_backend(graph_backend)
        if normalized_graph_backend and not _is_graph_backend_configured(normalized_graph_backend):
            return _error_response(
                400,
                f"graph backend is not configured: {normalized_graph_backend}",
            )
        try:
            resolved_minimum_nodes = _normalize_minimum_count(
                minimum_nodes,
                field_name="minimum_nodes",
                default=DEFAULT_MINIMUM_NODES,
            )
            resolved_minimum_edges = _normalize_minimum_count(
                minimum_edges,
                field_name="minimum_edges",
                default=DEFAULT_MINIMUM_EDGES,
            )
        except ValueError as exc:
            return _error_response(400, str(exc))

        if normalized_project_id:
            existing_project = ProjectManager.get_project(normalized_project_id)
            if not existing_project:
                return _error_response(404, f"Project not found: {normalized_project_id}")
            logger.info(f"Will reuse Project: {normalized_project_id}")

        resolved_prompt_label = PromptLabelManager.ensure_label_exists(
            OntologyGenerator._normalize_prompt_label(prompt_label)
        )

        task_manager = TaskManager()
        task_display_name = normalized_project_id or normalized_project_name
        task_id = task_manager.create_task(
            f"generate_ontology: {task_display_name}",
            metadata={"project_id": normalized_project_id} if normalized_project_id else None,
        )

        task_manager.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            message="Uploading files",
            progress=5,
            progress_detail={
                "step": "upload_pdf",
            },
        )

        staging_dir = os.path.join(Config.UPLOAD_FOLDER, "ontology_staging", task_id)
        os.makedirs(staging_dir, exist_ok=True)
        staged_files: list[dict[str, Any]] = []

        for upload in uploaded_files:
            if not allowed_file(upload.filename):
                continue

            ext = os.path.splitext(upload.filename)[1].lower()
            staged_filename = f"{uuid.uuid4().hex[:16]}{ext}"
            staged_path = os.path.join(staging_dir, staged_filename)
            upload.file.seek(0)
            with open(staged_path, "wb") as output:
                shutil.copyfileobj(upload.file, output)

            staged_files.append(
                {
                    "original_filename": upload.filename,
                    "path": staged_path,
                    "size": os.path.getsize(staged_path),
                }
            )

        if not staged_files:
            shutil.rmtree(staging_dir, ignore_errors=True)
            task_manager.update_task(
                task_id,
                status=TaskStatus.FAILED,
                message="No supported files were uploaded",
                progress=100,
                error="not successful, please check file format",
                progress_detail={
                    "step": "upload_pdf",
                },
            )
            return _error_response(400, "not successful, please check file format")

        total_files = len(staged_files)
        task_manager.update_task(
            task_id,
            message=f"Uploaded {total_files} file(s)",
            progress=10,
            progress_detail={
                "step": "upload_pdf",
                "uploaded_files": total_files,
                "total_files": total_files,
            },
        )

        def generate_task() -> None:
            project = None
            created_new_project = False
            try:
                task_manager.update_task(
                    task_id,
                    message="Processing uploaded files",
                    progress=15,
                    progress_detail={
                        "step": "process_pdf",
                        "processed_files": 0,
                        "total_files": total_files,
                    },
                )

                document_texts: list[str] = []
                extracted_sections: list[str] = []

                for index, staged_file in enumerate(staged_files, start=1):
                    process_progress = 15 + int((index / max(total_files, 1)) * 30)
                    task_manager.update_task(
                        task_id,
                        message=f"Processing file {index}/{total_files}: {staged_file['original_filename']}",
                        progress=process_progress,
                        progress_detail={
                            "step": "process_pdf",
                            "processed_files": index,
                            "total_files": total_files,
                        },
                    )

                    text = FileParser.extract_text(staged_file["path"])
                    text = TextProcessor.preprocess_text(text)
                    if text:
                        document_texts.append(text)
                        extracted_sections.append(
                            f"=== {staged_file['original_filename']} ===\n{text}"
                        )

                if not document_texts:
                    raise ValueError("not successful, please check file format")

                all_text = "\n\n".join(extracted_sections)

                task_manager.update_task(
                    task_id,
                    message="Creating project",
                    progress=50,
                    progress_detail={
                        "step": "create_project",
                    },
                )
                if normalized_project_id:
                    project = _timed_task_call(
                        task_manager,
                        task_id,
                        "step_a",
                        "ProjectManager.get_project",
                        ProjectManager.get_project,
                        normalized_project_id,
                    )
                    if not project:
                        raise ValueError(f"Project not found: {normalized_project_id}")
                    if normalized_project_name:
                        project.name = normalized_project_name
                    logger.info(f"Reusing Project: {project.project_id}")
                else:
                    project = _timed_task_call(
                        task_manager,
                        task_id,
                        "step_a",
                        "ProjectManager.create_project",
                        ProjectManager.create_project,
                        name=normalized_project_name,
                        persist=False,
                    )
                    created_new_project = True
                    logger.info(f"Prepared Project: {project.project_id}")

                project.context_requirement = requirement
                project.prompt_label = resolved_prompt_label
                project.minimum_nodes = resolved_minimum_nodes
                project.minimum_edges = resolved_minimum_edges
                if normalized_graph_backend:
                    project.graph_backend = normalized_graph_backend
                elif Config.ZEP_API_KEY:
                    project.graph_backend = "zep_cloud"
                else:
                    graphiti_db = str(Config.GRAPHITI_DB or "neo4j").strip().lower()
                    project.graph_backend = graphiti_db if graphiti_db in {"oracle", "neo4j"} else "neo4j"
                project.error = None

                task_manager.update_task(
                    task_id,
                    message=f"Project ready: {project.project_id}",
                    progress=60,
                    progress_detail={
                        "step": "create_project",
                        "project_id": project.project_id,
                    },
                )

                task_manager.update_task(
                    task_id,
                    message="Starting OntologyGenerator",
                    progress=70,
                    progress_detail={
                        "step": "ontology_generator",
                        "project_id": project.project_id,
                    },
                )
                generator = OntologyGenerator()
                ontology = generator.generate(
                    document_texts=document_texts,
                    context_requirement=requirement,
                    additional_context=additional_context or None,
                    minimum_nodes=resolved_minimum_nodes,
                    minimum_edges=resolved_minimum_edges,
                    prompt_label=project.prompt_label,
                    project_id=project.project_id,
                )

                entity_count = len(ontology.get("entity_types", []))
                edge_count = len(ontology.get("edge_types", []))
                logger.info(f"Ontology Generated: {entity_count} Entities, {edge_count} Edges")

                task_manager.update_task(
                    task_id,
                    message="Saving project data and ontology",
                    progress=90,
                    progress_detail={
                        "step": "save_project",
                        "project_id": project.project_id,
                        "entity_types": entity_count,
                        "edge_types": edge_count,
                    },
                )

                for staged_file in staged_files:
                    adapter = _LocalFileAdapter(staged_file["path"])
                    file_info = _timed_task_call(
                        task_manager,
                        task_id,
                        "step_a",
                        "ProjectManager.save_file_to_project",
                        ProjectManager.save_file_to_project,
                        project.project_id,
                        adapter,
                        staged_file["original_filename"],
                    )
                    project.files.append(
                        {
                            "filename": file_info["original_filename"],
                            "size": file_info["size"],
                        }
                    )

                project.total_text_length = len(all_text)
                _timed_task_call(
                    task_manager,
                    task_id,
                    "step_a",
                    "ProjectManager.save_extracted_text",
                    ProjectManager.save_extracted_text,
                    project.project_id,
                    all_text,
                )
                logger.info(f"Total Extracted Text: {len(all_text)} Words")

                project.ontology = {
                    "entity_types": ontology.get("entity_types", []),
                    "edge_types": ontology.get("edge_types", []),
                }
                project.analysis_summary = ontology.get("analysis_summary", "")
                project.status = ProjectStatus.ONTOLOGY_GENERATED
                _timed_task_call(
                    task_manager,
                    task_id,
                    "step_a",
                    "ProjectManager.save_project",
                    ProjectManager.save_project,
                    project,
                )
                logger.info(f"Ontology Generated Project[{project.project_id}]")

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="Ontology generation completed",
                    progress=100,
                    result={
                        "project_id": project.project_id,
                        "project_name": project.name,
                        "ontology": project.ontology,
                        "analysis_summary": project.analysis_summary,
                        "files": project.files,
                        "total_text_length": project.total_text_length,
                    },
                    progress_detail={
                        "step": "completed",
                        "project_id": project.project_id,
                    },
                )
            except Exception as exc:
                if created_new_project and project is not None:
                    _timed_task_call(
                        task_manager,
                        task_id,
                        "step_a",
                        "ProjectManager.delete_project",
                        ProjectManager.delete_project,
                        project.project_id,
                    )
                logger.exception("Ontology Generation Failed")
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"Ontology generation failed: {exc}",
                    progress=100,
                    error=traceback.format_exc(),
                    progress_detail={
                        "step": "failed",
                    },
                )
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        thread = threading.Thread(target=generate_task, daemon=True)
        thread.start()

        return {
            "success": True,
            "data": {
                "task_id": task_id,
                "message": f"Ontology Generate Task Started, please refer to /task/{task_id} for progress",
            },
        }
    except Exception as exc:
        logger.exception("Ontology Generate Request Failed")
        return _error_response(500, str(exc), exc)
