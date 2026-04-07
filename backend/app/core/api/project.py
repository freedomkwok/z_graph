import re
import os
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
from app.core.utils.chucking import (
    CHUNK_MODE_FIXED,
    CHUNK_MODE_HYBRID,
    CHUNK_MODE_SEMANTIC,
    normalize_chunk_mode,
    split_text_with_mode,
)
from app.core.utils.logger import get_logger
from app.core.utils.text_file_parser import FileParser
from app.core.utils.text_processor import TextProcessor

router = APIRouter()
logger = get_logger("z_graph.api")

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
PROJECT_NAME_GRAPH_ID_MAX_LENGTH = 120
PROJECT_NAME_GRAPH_ID_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
GRAPH_BACKEND_ZEP_CLOUD = "zep_cloud"
GRAPH_BACKEND_NEO4J = "neo4j"
GRAPH_BACKEND_ORACLE = "oracle"
GRAPHITI_BACKENDS = {GRAPH_BACKEND_NEO4J, GRAPH_BACKEND_ORACLE}
SUPPORTED_GRAPH_BACKENDS = {GRAPH_BACKEND_ZEP_CLOUD, *GRAPHITI_BACKENDS}
SUPPORTED_CHUNK_MODES = {CHUNK_MODE_FIXED, CHUNK_MODE_SEMANTIC, CHUNK_MODE_HYBRID}
ProjectPatchBody = Annotated[dict[str, Any], Body(default_factory=dict)]
DEV_APP_ENVS = {"dev", "development", "local"}


def _error_response(status_code: int, error: str, exc: Exception | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
    }
    if exc is not None:
        payload["traceback"] = traceback.format_exc()
    return JSONResponse(status_code=status_code, content=payload)


def _normalize_ontology_type_name(value: Any) -> str:
    return str(value or "").strip()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, int):
        return value != 0
    return False


def _build_project_name_graph_id(project_name: Any) -> str:
    normalized = PROJECT_NAME_GRAPH_ID_PATTERN.sub("-", str(project_name or "").strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-._")
    return normalized[:PROJECT_NAME_GRAPH_ID_MAX_LENGTH]


def _normalize_graph_backend(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_GRAPH_BACKENDS:
        return normalized
    return ""


def _is_supported_upload_file(upload: UploadFile) -> bool:
    filename = str(getattr(upload, "filename", "") or "").strip()
    if not filename or "." not in filename:
        return False
    extension = os.path.splitext(filename)[1].lower()
    return extension in FileParser.SUPPORTED_EXTENSIONS


def _default_graph_backend() -> str:
    if Config.ZEP_API_KEY:
        return GRAPH_BACKEND_ZEP_CLOUD

    configured_backend = str(Config.ZEP_BACKEND or "").strip().lower()
    if configured_backend == GRAPH_BACKEND_ZEP_CLOUD:
        return GRAPH_BACKEND_ZEP_CLOUD

    if configured_backend == "graphiti":
        configured_graphiti_db = str(Config.GRAPHITI_DB or "").strip().lower()
        if configured_graphiti_db in GRAPHITI_BACKENDS:
            return configured_graphiti_db
        return GRAPH_BACKEND_NEO4J

    return GRAPH_BACKEND_NEO4J


def _resolve_graph_backend(*candidates: Any) -> str:
    for value in candidates:
        normalized = _normalize_graph_backend(value)
        if normalized:
            return normalized
    return _default_graph_backend()


def _client_backend_for_graph_backend(graph_backend: str) -> str:
    return GRAPH_BACKEND_ZEP_CLOUD if graph_backend == GRAPH_BACKEND_ZEP_CLOUD else "graphiti"


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


@router.post("/project/draft")
def create_project_draft(
    files: list[UploadFile] = File(default_factory=list),
    project_name: str = Form("Unnamed Project"),
    prompt_label: str = Form("Production"),
    graph_backend: str = Form(""),
    project_id: str = Form(""),
) -> Any:
    try:
        normalized_project_id = str(project_id or "").strip()
        normalized_project_name = str(project_name or "").strip() or "Unnamed Project"
        normalized_graph_backend = _normalize_graph_backend(graph_backend)
        normalized_prompt_label = str(prompt_label or "").strip() or "Production"

        if normalized_project_id:
            project = ProjectManager.get_project(normalized_project_id)
            if not project:
                return _error_response(404, f"Project not found: {normalized_project_id}")
            created_new_project = False
        else:
            project = ProjectManager.create_project(name=normalized_project_name, persist=False)
            created_new_project = True

        project.name = normalized_project_name
        project.prompt_label = PromptLabelManager.ensure_label_exists(normalized_prompt_label)
        if normalized_graph_backend:
            project.graph_backend = normalized_graph_backend
        elif not _normalize_graph_backend(getattr(project, "graph_backend", None)):
            project.graph_backend = _default_graph_backend()

        uploaded_files: list[dict[str, Any]] = []
        extracted_sections: list[str] = []
        unsupported_files: list[str] = []
        for upload in files or []:
            if not upload or not upload.filename:
                continue
            if not _is_supported_upload_file(upload):
                unsupported_files.append(str(upload.filename))
                continue

            file_info = ProjectManager.save_file_to_project(
                project.project_id,
                upload,
                str(upload.filename),
            )
            uploaded_files.append(
                {
                    "filename": file_info["original_filename"],
                    "size": file_info["size"],
                }
            )
            try:
                extracted_text = FileParser.extract_text(file_info["path"])
                extracted_text = TextProcessor.preprocess_text(extracted_text)
                if extracted_text:
                    extracted_sections.append(
                        f"=== {file_info['original_filename']} ===\n{extracted_text}"
                    )
            except Exception as exc:
                logger.warning(
                    "Skip extracted text for file '%s': %s",
                    file_info["original_filename"],
                    str(exc),
                )

        if uploaded_files:
            existing_files = list(project.files or [])
            project.files = [*existing_files, *uploaded_files]

        existing_text = TextProcessor.preprocess_text(
            ProjectManager.get_extracted_text(project.project_id) or ""
        )
        if extracted_sections:
            new_text = "\n\n".join(extracted_sections)
            merged_text = (
                f"{existing_text}\n\n{new_text}".strip() if existing_text else new_text
            )
            ProjectManager.save_extracted_text(project.project_id, merged_text)
            project.total_text_length = len(merged_text)
        elif existing_text:
            project.total_text_length = len(existing_text)

        ProjectManager.save_project(project)
        return {
            "success": True,
            "message": "Draft project prepared",
            "data": {
                **_build_project_response_data(project),
                "created_new_project": created_new_project,
                "uploaded_files": len(uploaded_files),
                "unsupported_files": unsupported_files,
            },
        }
    except Exception as exc:
        logger.exception("Failed to prepare draft project")
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

        requested_graph_backend = _normalize_graph_backend(data.get("graph_backend"))
        project_graph_backend = _normalize_graph_backend(getattr(project, "graph_backend", None))
        resolved_graph_backend = _resolve_graph_backend(
            project_graph_backend,
            requested_graph_backend,
        )
        if (
            project_graph_backend
            and requested_graph_backend
            and project_graph_backend != requested_graph_backend
        ):
            logger.warning(
                "Ignoring requested graph_backend '%s' for project %s; using stored backend '%s'",
                requested_graph_backend,
                project_id,
                project_graph_backend,
            )
        client_backend = _client_backend_for_graph_backend(resolved_graph_backend)

        requested_graph_id = str(data.get("graph_id") or "").strip()
        existing_graph_id = str(project.zep_graph_id or "").strip()
        use_project_name_as_graph_id = _coerce_bool(data.get("use_project_name_as_graph_id"))

        project_name_graph_id = ""
        if use_project_name_as_graph_id:
            if resolved_graph_backend == GRAPH_BACKEND_ZEP_CLOUD:
                project_name_graph_id = _build_project_name_graph_id(project.name)
                if not project_name_graph_id:
                    return _error_response(
                        400,
                        "project name cannot be converted to a valid graph id for zep_cloud",
                    )
            else:
                logger.info(
                    "Ignoring use_project_name_as_graph_id because backend is '%s'",
                    resolved_graph_backend or "unknown",
                )

        resolved_graph_id = project_name_graph_id or requested_graph_id or existing_graph_id or None

        graph_name = data.get("graph_name", project.name or "imp Graph")
        chunk_size = int(data.get("chunk_size", project.chunk_size or DEFAULT_CHUNK_SIZE))
        chunk_overlap = int(
            data.get("chunk_overlap", project.chunk_overlap or DEFAULT_CHUNK_OVERLAP)
        )
        chunk_mode = normalize_chunk_mode(data.get("chunk_mode", getattr(project, "chunk_mode", None)))
        if chunk_mode not in SUPPORTED_CHUNK_MODES:
            chunk_mode = CHUNK_MODE_FIXED

        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        project.chunk_mode = chunk_mode
        project.graph_backend = resolved_graph_backend

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

                build_logger.info(
                    "[%s] Using backend=%s graph_backend=%s for project_id=%s",
                    task_id,
                    client_backend,
                    resolved_graph_backend,
                    project_id,
                )
                builder = GraphBuilderService(
                    backend=client_backend,
                    graph_backend=resolved_graph_backend,
                    api_key=Config.ZEP_API_KEY,
                )

                task_manager.update_task(
                    task_id,
                    message=f"Splitting Text ({chunk_mode} mode)",
                    progress=5,
                )
                chunks = split_text_with_mode(
                    text,
                    chunk_size=chunk_size,
                    overlap=chunk_overlap,
                    chunk_mode=chunk_mode,
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
                        "graph_backend": resolved_graph_backend,
                        "chunk_mode": chunk_mode,
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
    graph_backend: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
) -> Any:
    try:
        normalized_workspace_id = str(project_workspace_id or "").strip() or None
        normalized_project_id = str(project_id or "").strip()
        project_graph_backend = ""
        if normalized_project_id:
            project = ProjectManager.get_project(normalized_project_id)
            if project is not None:
                project_graph_backend = str(getattr(project, "graph_backend", "") or "")

        requested_graph_backend = _normalize_graph_backend(graph_backend)
        resolved_graph_backend = _resolve_graph_backend(
            project_graph_backend,
            requested_graph_backend,
            GRAPH_BACKEND_ZEP_CLOUD if normalized_workspace_id else None,
        )
        if (
            project_graph_backend
            and requested_graph_backend
            and project_graph_backend != requested_graph_backend
        ):
            logger.warning(
                "Ignoring requested graph_backend '%s' for project %s in /data; using stored backend '%s'",
                requested_graph_backend,
                normalized_project_id,
                project_graph_backend,
            )
        primary_backend = _client_backend_for_graph_backend(resolved_graph_backend)

        def _load_graph_data(selected_backend: str, selected_graph_backend: str) -> dict[str, Any]:
            builder = GraphBuilderService(
                backend=selected_backend,
                graph_backend=selected_graph_backend,
                api_key=Config.ZEP_API_KEY,
            )
            return builder.get_graph_data(
                graph_id,
                include_episode_data=include_episode_data,
                project_workspace_id=normalized_workspace_id,
            )

        logger.info(
            "Loading graph data with backend=%s graph_backend=%s graph_id=%s project_id=%s",
            primary_backend,
            resolved_graph_backend,
            graph_id,
            normalized_project_id or "-",
        )
        graph_data = _load_graph_data(primary_backend, resolved_graph_backend)

        return {
            "success": True,
            "data": graph_data,
        }
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            return _error_response(404, f"Graph not found: {graph_id}")
        logger.exception("Failed to get graph data")
        return _error_response(500, str(exc), exc)


@router.delete("/delete/{graph_id}")
def delete_graph(
    graph_id: str,
    graph_backend: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
) -> Any:
    try:
        if not Config.ZEP_API_KEY:
            return _error_response(500, "ZEP_API_KEY not configured")

        normalized_project_id = str(project_id or "").strip()
        project_graph_backend = ""
        if normalized_project_id:
            project = ProjectManager.get_project(normalized_project_id)
            if project is not None:
                project_graph_backend = str(getattr(project, "graph_backend", "") or "")
        requested_graph_backend = _normalize_graph_backend(graph_backend)
        resolved_graph_backend = _resolve_graph_backend(project_graph_backend, requested_graph_backend)
        if (
            project_graph_backend
            and requested_graph_backend
            and project_graph_backend != requested_graph_backend
        ):
            logger.warning(
                "Ignoring requested graph_backend '%s' for project %s in /delete; using stored backend '%s'",
                requested_graph_backend,
                normalized_project_id,
                project_graph_backend,
            )

        builder = GraphBuilderService(
            backend=_client_backend_for_graph_backend(resolved_graph_backend),
            graph_backend=resolved_graph_backend,
            api_key=Config.ZEP_API_KEY,
        )
        builder.delete_graph(graph_id)
        return {
            "success": True,
            "message": f"Graph deleted: {graph_id}",
        }
    except Exception as exc:
        logger.exception("Failed to delete graph")
        return _error_response(500, str(exc), exc)
