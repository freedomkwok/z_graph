"""
Copyright (c) 2026 Richard G and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import os
import shutil
import threading
import time
import traceback
import uuid
import hashlib
import json
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
from app.core.utils.db_query import insert_ontology_version_data

router = APIRouter()
logger = get_logger("z_graph.api.ontology")

DEFAULT_MINIMUM_NODES = 10
DEFAULT_MINIMUM_EDGES = 10
DEV_APP_ENVS = {"dev", "development", "local"}
SUPPORTED_GRAPH_BACKENDS = {"zep_cloud", "neo4j", "oracle"}


class TaskCancelledError(RuntimeError):
    """Raised when a user cancels a running ontology task."""


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


def _normalize_pdf_page(value: Any, *, field_name: str, default: int | None = None) -> int | None:
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


def _raise_if_task_cancelled(task_manager: TaskManager, task_id: str) -> None:
    if task_manager.is_cancelled(task_id):
        raise TaskCancelledError("Ontology generation cancelled by user")


def _compute_ontology_hash(ontology: dict[str, Any]) -> str:
    canonical = json.dumps(ontology or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    pdf_page_from: int | None = Form(None),
    pdf_page_to: int | None = Form(None),
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
            resolved_pdf_page_from = _normalize_pdf_page(
                pdf_page_from,
                field_name="pdf_page_from",
                default=None,
            )
            resolved_pdf_page_to = _normalize_pdf_page(
                pdf_page_to,
                field_name="pdf_page_to",
                default=None,
            )
        except ValueError as exc:
            return _error_response(400, str(exc))
        if (
            resolved_pdf_page_from is not None
            and resolved_pdf_page_to is not None
            and resolved_pdf_page_from > resolved_pdf_page_to
        ):
            resolved_pdf_page_from, resolved_pdf_page_to = (
                resolved_pdf_page_to,
                resolved_pdf_page_from,
            )

        if normalized_project_id:
            existing_project = ProjectManager.get_project(normalized_project_id)
            if not existing_project:
                return _error_response(404, f"Project not found: {normalized_project_id}")
            logger.info(f"Will reuse Project: {normalized_project_id}")

        resolved_prompt_label = PromptLabelManager.create_label(
            OntologyGenerator._normalize_prompt_label(prompt_label)
        )
        resolved_prompt_label_name = str(
            (resolved_prompt_label or {}).get("name")
            or OntologyGenerator._normalize_prompt_label(prompt_label)
        )
        resolved_prompt_label_id = (
            int((resolved_prompt_label or {}).get("id"))
            if (resolved_prompt_label or {}).get("id") is not None
            else None
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
                _raise_if_task_cancelled(task_manager, task_id)
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
                    _raise_if_task_cancelled(task_manager, task_id)
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

                    text = FileParser.extract_text(
                        staged_file["path"],
                        pdf_page_from=resolved_pdf_page_from,
                        pdf_page_to=resolved_pdf_page_to,
                    )
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
                _raise_if_task_cancelled(task_manager, task_id)
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
                project.prompt_label = resolved_prompt_label_name
                project.prompt_label_id = resolved_prompt_label_id
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

                # Persist project-level run settings as soon as Step A starts.
                # This guarantees Simulation Requirement and related fields are saved
                # even if ontology generation later fails for an existing project.
                task_manager.update_task(
                    task_id,
                    message="Saving project settings",
                    progress=55,
                    progress_detail={
                        "step": "save_project_settings",
                        "project_id": project.project_id,
                    },
                )
                _timed_task_call(
                    task_manager,
                    task_id,
                    "step_a",
                    "ProjectManager.save_project",
                    ProjectManager.save_project,
                    project,
                )

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
                _raise_if_task_cancelled(task_manager, task_id)
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
                    _raise_if_task_cancelled(task_manager, task_id)
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
                ontology_version_id = None
                if ProjectManager._use_postgres_storage():
                    ontology_hash = _compute_ontology_hash(project.ontology)
                    ontology_version_row = insert_ontology_version_data(
                        ProjectManager._get_storage_connection_string(),
                        project_id=project.project_id,
                        source="generated",
                        ontology_json=project.ontology,
                        ontology_hash=ontology_hash,
                        created_by_task_id=task_id,
                    )
                    ontology_version_id = int(ontology_version_row.get("id") or 0) or None
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
                        "ontology_version_id": ontology_version_id,
                    },
                    progress_detail={
                        "step": "completed",
                        "project_id": project.project_id,
                        "ontology_version_id": ontology_version_id,
                    },
                )
            except TaskCancelledError:
                logger.info("Ontology Generation Cancelled: task_id=%s", task_id)
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.CANCELLED,
                    message="Ontology generation cancelled by user",
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
