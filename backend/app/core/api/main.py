import os
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Annotated, Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Body, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import Config
from app.core.managers.prompt_label_manager import PromptLabelManager
from app.core.managers.project_manager import ProjectManager
from app.core.managers.task_manager import TaskManager
from app.core.schemas.project import ProjectStatus
from app.core.schemas.task import TaskStatus
from app.core.service.graph_builder import GraphBuilderService
from app.core.service.ontology_generator import OntologyGenerator
from app.core.utils.logger import get_logger
from app.core.utils.text_file_parser import FileParser
from app.core.utils.text_processor import TextProcessor

router = APIRouter()
logger = get_logger("z_graph.api")

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_MINIMUM_NODES = 10
DEFAULT_MINIMUM_EDGES = 10
ProjectPatchBody = Annotated[dict[str, Any], Body(default_factory=dict)]
DEV_APP_ENVS = {"dev", "development", "local"}


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


def _normalize_ontology_type_name(value: Any) -> str:
    return str(value or "").strip()


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


def _sanitize_ontology_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("ontology must be an object")

    raw_entity_types = payload.get("entity_types", [])
    raw_edge_types = payload.get("edge_types", [])
    if not isinstance(raw_entity_types, list):
        raise ValueError("ontology.entity_types must be a list")
    if not isinstance(raw_edge_types, list):
        raise ValueError("ontology.edge_types must be a list")

    entity_types: list[dict[str, Any]] = []
    for raw_entity in raw_entity_types:
        if not isinstance(raw_entity, dict):
            continue
        name = _normalize_ontology_type_name(raw_entity.get("name"))
        if not name:
            continue
        entity = dict(raw_entity)
        entity["name"] = name
        if not isinstance(entity.get("attributes"), list):
            entity["attributes"] = []
        if not isinstance(entity.get("examples"), list):
            entity["examples"] = []
        entity_types.append(entity)

    edge_types: list[dict[str, Any]] = []
    for raw_edge in raw_edge_types:
        if not isinstance(raw_edge, dict):
            continue
        name = _normalize_ontology_type_name(raw_edge.get("name"))
        if not name:
            continue
        edge = dict(raw_edge)
        edge["name"] = name
        if not isinstance(edge.get("attributes"), list):
            edge["attributes"] = []
        raw_source_targets = edge.get("source_targets", [])
        source_targets: list[dict[str, str]] = []
        if isinstance(raw_source_targets, list):
            for raw_source_target in raw_source_targets:
                if not isinstance(raw_source_target, dict):
                    continue
                source = _normalize_ontology_type_name(raw_source_target.get("source"))
                target = _normalize_ontology_type_name(raw_source_target.get("target"))
                if not source or not target:
                    continue
                source_targets.append({"source": source, "target": target})
        edge["source_targets"] = source_targets
        edge_types.append(edge)

    return {
        "entity_types": entity_types,
        "edge_types": edge_types,
    }


def _build_zep_graph_address(graph_id: str, project_workspace_id: str | None = None) -> str:
    template = str(Config.ZEP_GRAPH_URL_TEMPLATE or "").strip()
    if template:
        if "{graph_id}" in template or "{project_workspace_id}" in template:
            try:
                return template.format(
                    graph_id=graph_id,
                    project_workspace_id=project_workspace_id or "",
                )
            except KeyError:
                return template
        return template
    if project_workspace_id:
        return (
            "https://app.getzep.com/projects/"
            f"{quote(project_workspace_id, safe='')}/graphs/{quote(graph_id, safe='')}"
        )
    # Fallback keeps existing behavior while carrying graph id for deep-link support.
    return f"https://app.getzep.com/?graph_id={quote(graph_id, safe='')}"


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


def _build_project_response_data(project: Any) -> dict[str, Any]:
    project_data = project.to_dict()
    project_data["prompt_label_info"] = PromptLabelManager.get_project_label_info(
        label_name=project_data.get("prompt_label"),
        project_id=project_data.get("project_id"),
    )
    return project_data


@router.get("/project/list")
def list_projects(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    projects = ProjectManager.list_projects(limit=limit)
    return {
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects),
    }


@router.get("/prompt-label/list")
def list_prompt_labels() -> dict[str, Any]:
    labels = PromptLabelManager.list_labels()
    label_stats = PromptLabelManager.get_label_stats()
    total_labels = int(label_stats.get("total_labels") or len(labels))
    return {
        "success": True,
        "data": labels,
        "count": len(labels),
        "total_labels": total_labels,
        "stats": label_stats,
    }


@router.post("/prompt-label")
def create_prompt_label(data: ProjectPatchBody) -> Any:
    try:
        name = (data or {}).get("name")
        label = PromptLabelManager.create_label(str(name or ""))
        return {
            "success": True,
            "message": f"Category label saved: {label['name']}",
            "data": label,
        }
    except Exception as exc:
        return _error_response(400, str(exc), exc)


@router.delete("/prompt-label/{label_name}")
def delete_prompt_label(label_name: str) -> Any:
    success, message = PromptLabelManager.delete_label(label_name)
    if not success:
        return _error_response(409, message)
    return {
        "success": True,
        "message": message,
    }


@router.post("/prompt-label/{label_name}/sync-from-langfuse")
def sync_prompt_label_from_langfuse(label_name: str) -> Any:
    try:
        result = PromptLabelManager.sync_label_from_langfuse(label_name)
        return {
            "success": True,
            "message": f"Category label synced from Langfuse: {result.get('requested_label')}",
            "data": result,
        }
    except Exception as exc:
        logger.exception("Category label sync from Langfuse failed")
        return _error_response(500, str(exc), exc)


@router.get("/prompt-label/{label_name}/types")
def get_prompt_label_types(label_name: str) -> Any:
    try:
        data = PromptLabelManager.get_label_type_lists(label_name)
        return {
            "success": True,
            "data": data,
        }
    except Exception as exc:
        return _error_response(400, str(exc), exc)


@router.patch("/prompt-label/{label_name}/types")
def update_prompt_label_types(label_name: str, data: ProjectPatchBody) -> Any:
    try:
        result = PromptLabelManager.update_label_type_lists(label_name, data)
        return {
            "success": True,
            "message": f"Category label type lists updated: {result.get('label_name')}",
            "data": result,
        }
    except ValueError as exc:
        return _error_response(400, str(exc))
    except Exception as exc:
        logger.exception("Category label type update failed")
        return _error_response(500, str(exc), exc)


@router.get("/project/{project_id}")
def get_project(project_id: str) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")
    return {
        "success": True,
        "data": _build_project_response_data(project),
    }


@router.patch("/project/{project_id}")
def update_project(project_id: str, data: ProjectPatchBody) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")

    name = str((data or {}).get("name", "")).strip()
    prompt_label = str((data or {}).get("prompt_label", "")).strip()
    raw_ontology = (data or {}).get("ontology")
    has_ontology = raw_ontology is not None
    if not name and not prompt_label and not has_ontology:
        return _error_response(400, "At least one field is required: name, prompt_label, or ontology")

    if name:
        project.name = name
    if prompt_label:
        project.prompt_label = PromptLabelManager.ensure_label_exists(prompt_label)
    if has_ontology:
        try:
            project.ontology = _sanitize_ontology_payload(raw_ontology)
        except ValueError as exc:
            return _error_response(400, str(exc))

        # Ontology edits require rebuilding graph with the updated schema.
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        project.zep_graph_id = None
        project.project_workspace_id = None
        project.zep_graph_address = None
        project.graph_build_task_id = None
        project.error = None

    ProjectManager.save_project(project)
    return {
        "success": True,
        "message": f"Project updated: {project_id}",
        "data": _build_project_response_data(project),
    }


@router.delete("/project/{project_id}")
def delete_project(project_id: str) -> Any:
    success = ProjectManager.delete_project(project_id)
    if not success:
        return _error_response(404, f"Project not found or delete failed: {project_id}")
    return {
        "success": True,
        "message": f"Project deleted: {project_id}",
    }


@router.post("/project/{project_id}/reset")
def reset_project(project_id: str) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")

    project.status = ProjectStatus.ONTOLOGY_GENERATED if project.ontology else ProjectStatus.CREATED
    project.zep_graph_id = None
    project.project_workspace_id = None
    project.zep_graph_address = None
    project.graph_build_task_id = None
    project.error = None
    ProjectManager.save_project(project)

    return {
        "success": True,
        "message": f"Project Reset: {project_id}",
        "data": _build_project_response_data(project),
    }


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


@router.post("/build")
def build_graph(data: dict[str, Any] = Body(default_factory=dict)) -> Any:
    try:
        logger.info("----------------Start building graph----------------")

        if not Config.ZEP_API_KEY:
            return _error_response(500, "ZEP_API_KEY not configured")

        project_id = data.get("project_id")
        if not project_id:
            return _error_response(400, "missing project_id")

        project = ProjectManager.get_project(project_id)
        if not project:
            return _error_response(404, f"Project not found: {project_id}")

        force = bool(data.get("force", False))
        if project.status == ProjectStatus.CREATED:
            return _error_response(400, "missing ontology, please refer to /ontology/generate")

        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Graph is building, force rebuild use `force: true`",
                    "task_id": project.graph_build_task_id,
                },
            )

        if force and project.status in {
            ProjectStatus.GRAPH_BUILDING,
            ProjectStatus.FAILED,
            ProjectStatus.GRAPH_COMPLETED,
        }:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.zep_graph_id = None
            project.project_workspace_id = None
            project.zep_graph_address = None
            project.graph_build_task_id = None
            project.error = None

        requested_graph_id = str(data.get("graph_id") or "").strip()
        existing_graph_id = str(project.zep_graph_id or "").strip()
        resolved_graph_id = requested_graph_id or existing_graph_id or None

        graph_name = data.get("graph_name", project.name or "imp Graph")
        chunk_size = int(data.get("chunk_size", project.chunk_size or DEFAULT_CHUNK_SIZE))
        chunk_overlap = int(
            data.get("chunk_overlap", project.chunk_overlap or DEFAULT_CHUNK_OVERLAP)
        )

        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap

        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return _error_response(400, "no extracted text")

        ontology = project.ontology
        if not ontology:
            return _error_response(400, "no ontology")

        task_manager = TaskManager()
        task_id = task_manager.create_task(f"build_graph: {graph_name}")
        logger.info(f"create build_graph task: task_id={task_id}, project_id={project_id}")

        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        _timed_task_call(
            task_manager,
            task_id,
            "step_b",
            "ProjectManager.save_project",
            ProjectManager.save_project,
            project,
        )

        def build_task() -> None:
            build_logger = get_logger("z_graph.build")
            try:
                build_logger.info(f"[{task_id}] Start building graph")
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    message="Initializing graph build service",
                )

                builder = GraphBuilderService(backend=Config.ZEP_BACKEND ,api_key=Config.ZEP_API_KEY)

                task_manager.update_task(task_id, message="Splitting Text", progress=5)
                chunks = TextProcessor.split_text(
                    text,
                    chunk_size=chunk_size,
                    overlap=chunk_overlap,
                )
                total_chunks = len(chunks)

                task_manager.update_task(task_id, message="Creating Zep Graph", progress=10)
                graph_id, project_workspace_id = builder.create_graph(
                    name=graph_name,
                    project_id=project_id,
                    graph_id=resolved_graph_id,
                )

                project.zep_graph_id = graph_id
                project.project_workspace_id = project_workspace_id
                project.zep_graph_address = _build_zep_graph_address(
                    graph_id, project_workspace_id=project_workspace_id
                )
                _timed_task_call(
                    task_manager,
                    task_id,
                    "step_b",
                    "ProjectManager.save_project",
                    ProjectManager.save_project,
                    project,
                )

                task_manager.update_task(task_id, message="Setting Ontology", progress=15)
                builder.set_ontology(graph_id, ontology)

                def add_progress_callback(message: str, progress_ratio: float) -> None:
                    progress = 15 + int(progress_ratio * 40)
                    task_manager.update_task(task_id, message=message, progress=progress)

                task_manager.update_task(
                    task_id,
                    message=f"Adding {total_chunks} chunks",
                    progress=15,
                )
                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback,
                )

                task_manager.update_task(task_id, message="Waiting for Zep to process data", progress=45)

                def wait_progress_callback(message: str, progress_ratio: float) -> None:
                    progress = 55 + int(progress_ratio * 35)
                    task_manager.update_task(task_id, message=message, progress=progress)

                builder._wait_for_episodes(episode_uuids, wait_progress_callback)

                task_manager.update_task(task_id, message="Getting Graph Data", progress=90)
                graph_data = builder.get_graph_data(graph_id, include_episode_data=False)

                project.status = ProjectStatus.GRAPH_COMPLETED
                _timed_task_call(
                    task_manager,
                    task_id,
                    "step_b",
                    "ProjectManager.save_project",
                    ProjectManager.save_project,
                    project,
                )

                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(
                    f"[{task_id}] Graph Build Completed: graph_id={graph_id}, nodes={node_count}, edges={edge_count}"
                )

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="Graph Build Completed",
                    progress=100,
                    result={
                        "project_id": project_id,
                        "zep_graph_id": graph_id,
                        "project_workspace_id": project_workspace_id,
                        "zep_graph_address": project.zep_graph_address,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks,
                    },
                )
            except Exception as exc:
                build_logger.error(f"[{task_id}] Graph Build Failed: {exc}")
                build_logger.debug(traceback.format_exc())

                project.status = ProjectStatus.FAILED
                project.error = str(exc)
                _timed_task_call(
                    task_manager,
                    task_id,
                    "step_b",
                    "ProjectManager.save_project",
                    ProjectManager.save_project,
                    project,
                )

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"Graph Build Failed: {exc}",
                    error=traceback.format_exc(),
                )

        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()

        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": "Graph Build Task Started, please refer to /task/{task_id} for progress",
            },
        }
    except Exception as exc:
        logger.exception("Graph Build Request Failed")
        return _error_response(500, str(exc), exc)


@router.get("/task/{task_id}")
def get_task(task_id: str) -> Any:
    task = TaskManager().get_task(task_id)
    if not task:
        return _error_response(404, f"Task not found: {task_id}")
    return {
        "success": True,
        "data": task.to_dict(),
    }


@router.get("/tasks")
def list_tasks() -> dict[str, Any]:
    tasks = TaskManager().list_tasks()
    return {
        "success": True,
        "data": tasks,
        "count": len(tasks),
    }


@router.get("/data/{graph_id}")
def get_graph_data(
    graph_id: str,
    include_episode_data: bool = Query(default=True),
    project_workspace_id: str | None = Query(default=None),
) -> Any:
    try:
        backend = "zep_cloud" if project_workspace_id else Config.ZEP_BACKEND
        builder = GraphBuilderService(backend=backend, api_key=Config.ZEP_API_KEY)
        graph_data = builder.get_graph_data(
            graph_id,
            include_episode_data=include_episode_data,
        )
        return {
            "success": True,
            "data": graph_data,
        }
    except Exception as exc:
        logger.exception("Failed to get graph data")
        return _error_response(500, str(exc), exc)


@router.delete("/delete/{graph_id}")
def delete_graph(graph_id: str) -> Any:
    try:
        if not Config.ZEP_API_KEY:
            return _error_response(500, "ZEP_API_KEY not configured")

        builder = GraphBuilderService(backend=Config.ZEP_BACKEND ,api_key=Config.ZEP_API_KEY)
        builder.delete_graph(graph_id)
        return {
            "success": True,
            "message": f"Graph deleted: {graph_id}",
        }
    except Exception as exc:
        logger.exception("Failed to delete graph")
        return _error_response(500, str(exc), exc)
