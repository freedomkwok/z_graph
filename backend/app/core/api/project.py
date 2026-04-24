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

import re
import os
import hashlib
import json
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Annotated, Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, Body, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.core.backend_client_factory.client_factory import get_or_create_zep_client
from app.core.config import Config
from app.core.managers.prompt_label_manager import PromptLabelManager
from app.core.managers.batch_process_manager import BatchProcessManager
from app.core.managers.project_manager import ProjectManager
from app.core.managers.task_manager import TaskManager
from app.core.schemas.project import ProjectStatus
from app.core.schemas.task import TaskStatus
from app.core.service.graph_builder import GraphBuilderService, TaskCancelledError
from app.core.utils.chucking import (
    CHUNK_MODE_FIXED,
    CHUNK_MODE_HYBRID,
    CHUNK_MODE_LLAMA_INDEX,
    CHUNK_MODE_SEMANTIC,
    normalize_chunk_mode,
    split_text_with_mode,
)
from app.core.utils.logger import get_logger
from app.core.utils.text_file_parser import FileParser
from app.core.utils.text_processor import TextProcessor
from app.core.utils.db_query import (
    get_latest_graph_build_resume_candidate,
    get_latest_ontology_version_data,
    insert_ontology_version_data,
    list_ontology_versions_data,
    merge_project_data_json_fields,
)

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
SUPPORTED_CHUNK_MODES = {
    CHUNK_MODE_FIXED,
    CHUNK_MODE_SEMANTIC,
    CHUNK_MODE_HYBRID,
    CHUNK_MODE_LLAMA_INDEX,
}
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


def _coerce_optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _resolve_oracle_runtime_settings(
    project: Any,
    *,
    use_project_overrides: bool | None = None,
) -> dict[str, int | None]:
    runtime_overrides_enabled = use_project_overrides
    if runtime_overrides_enabled is None:
        runtime_overrides_enabled = getattr(project, "enable_oracle_runtime_overrides", True)
    runtime_overrides_enabled = bool(runtime_overrides_enabled)

    if not runtime_overrides_enabled:
        return {
            "oracle_pool_min": _coerce_optional_positive_int(Config.ORACLE_POOL_MIN),
            "oracle_pool_max": _coerce_optional_positive_int(Config.ORACLE_POOL_MAX),
            "oracle_pool_increment": _coerce_optional_positive_int(Config.ORACLE_POOL_INCREMENT),
            "oracle_max_coroutines": _coerce_optional_positive_int(Config.ORACLE_MAX_COROUTINES),
        }

    return {
        "oracle_pool_min": (
            _coerce_optional_positive_int(getattr(project, "oracle_pool_min", None))
            or _coerce_optional_positive_int(Config.ORACLE_POOL_MIN)
        ),
        "oracle_pool_max": (
            _coerce_optional_positive_int(getattr(project, "oracle_pool_max", None))
            or _coerce_optional_positive_int(Config.ORACLE_POOL_MAX)
        ),
        "oracle_pool_increment": (
            _coerce_optional_positive_int(getattr(project, "oracle_pool_increment", None))
            or _coerce_optional_positive_int(Config.ORACLE_POOL_INCREMENT)
        ),
        "oracle_max_coroutines": (
            _coerce_optional_positive_int(getattr(project, "oracle_max_coroutines", None))
            or _coerce_optional_positive_int(Config.ORACLE_MAX_COROUTINES)
        ),
    }


def _looks_like_missing_graph_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "not found" in message or "404" in message


def _build_project_name_graph_id(project_name: Any) -> str:
    normalized = PROJECT_NAME_GRAPH_ID_PATTERN.sub("-", str(project_name or "").strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-._")
    return normalized[:PROJECT_NAME_GRAPH_ID_MAX_LENGTH]


def _normalize_graph_backend(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_GRAPH_BACKENDS:
        return normalized
    return ""


def _normalize_graph_search_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"all", "node", "edge", "episode"}:
        return normalized
    return "all"


def _build_text_match_score(text: str, query: str) -> int:
    normalized_text = str(text or "").strip().lower()
    normalized_query = str(query or "").strip().lower()
    if not normalized_text or not normalized_query:
        return 0
    score = 0
    if normalized_query in normalized_text:
        score += 100
    keywords = [
        token.strip()
        for token in normalized_query.replace(",", " ").replace("，", " ").split()
        if len(token.strip()) > 1
    ]
    for keyword in keywords:
        if keyword in normalized_text:
            score += 12
    return score


def _serialize_episode_payload(episode: Any, fallback_uuid: str) -> dict[str, Any]:
    model_data: dict[str, Any] = {}
    if hasattr(episode, "model_dump"):
        try:
            model_data = episode.model_dump(mode="json", exclude_none=False)
        except TypeError:
            model_data = episode.model_dump()
        except Exception:
            model_data = {}
    elif hasattr(episode, "dict"):
        try:
            model_data = episode.dict()
        except Exception:
            model_data = {}
    elif hasattr(episode, "__dict__"):
        model_data = dict(getattr(episode, "__dict__", {}) or {})

    episode_uuid = getattr(episode, "uuid_", None) or getattr(episode, "uuid", None) or fallback_uuid
    payload = {
        "uuid": str(episode_uuid),
        "processed": getattr(episode, "processed", None),
        "type": getattr(episode, "type", None),
        "data": getattr(episode, "data", None),
        "source": getattr(episode, "source", None),
        "source_description": getattr(episode, "source_description", None),
        "created_at": getattr(episode, "created_at", None),
        "reference_time": getattr(episode, "reference_time", None),
    }
    if isinstance(model_data, dict):
        for key, value in model_data.items():
            if key not in payload:
                payload[key] = value
    return payload


def _collect_episode_search_hits(
    *,
    builder: GraphBuilderService,
    query: str,
    episode_node_anchors: dict[str, set[str]],
    episode_limit: int,
) -> list[dict[str, Any]]:
    if not episode_node_anchors:
        return []
    episode_namespace = getattr(getattr(builder.client, "graph", None), "episode", None)
    get_episode = getattr(episode_namespace, "get", None)
    if not callable(get_episode):
        return []

    scored_items: list[tuple[int, dict[str, Any]]] = []
    for episode_id, anchor_node_ids in episode_node_anchors.items():
        normalized_episode_id = str(episode_id or "").strip()
        if not normalized_episode_id:
            continue
        try:
            episode = get_episode(uuid_=normalized_episode_id)
        except Exception:
            continue
        episode_payload = _serialize_episode_payload(episode, normalized_episode_id)
        raw_data = str(episode_payload.get("data") or "")
        source_description = str(episode_payload.get("source_description") or "").strip()
        source_value = str(episode_payload.get("source") or "").strip()
        searchable_text = " ".join(
            [
                normalized_episode_id,
                raw_data,
                source_description,
                source_value,
            ]
        )
        score = _build_text_match_score(searchable_text, query)
        if score <= 0:
            continue
        preview_text = raw_data.strip().replace("\n", " ")
        if len(preview_text) > 180:
            preview_text = f"{preview_text[:177]}..."
        scored_items.append(
            (
                score,
                {
                    "id": normalized_episode_id,
                    "subtitle": source_description or source_value or "Episode",
                    "preview": preview_text,
                    "score": score,
                    "anchor_node_ids": sorted(anchor_node_ids),
                },
            )
        )
    scored_items.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [item[1] for item in scored_items[: max(1, int(episode_limit or 1))]]


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


def _graph_backend_display_name(graph_backend: str) -> str:
    normalized = _normalize_graph_backend(graph_backend)
    if normalized == GRAPH_BACKEND_ZEP_CLOUD:
        return "Zep Cloud"
    if normalized == GRAPH_BACKEND_NEO4J:
        return "Neo4j"
    if normalized == GRAPH_BACKEND_ORACLE:
        return "Oracle"
    return "Graph Backend"


def _require_project_id_for_oracle_backend(
    resolved_graph_backend: str,
    project_id: str,
    *,
    route_name: str,
) -> JSONResponse | None:
    if _normalize_graph_backend(resolved_graph_backend) != GRAPH_BACKEND_ORACLE:
        return None
    if str(project_id or "").strip():
        return None
    return _error_response(
        400,
        f"project_id is required for Oracle graph backend in {route_name}",
    )


def _normalize_graphiti_embedding_model(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return normalized


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


def _resolve_graphiti_embedding_model(*candidates: Any) -> str:
    allowed = set(Config.GRAPHITI_EMBEDDING_MODELS)
    for value in candidates:
        normalized = _normalize_graphiti_embedding_model(value)
        if not normalized:
            continue
        if normalized in allowed:
            return normalized
        logger.warning(
            "Ignoring unsupported graphiti embedding model '%s'; allowed=%s",
            normalized,
            Config.GRAPHITI_EMBEDDING_MODELS,
        )
    return Config.GRAPHITI_DEFAULT_EMBEDDING_MODEL


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


def _is_task_cancelled(task_manager: TaskManager, task_id: str) -> bool:
    return task_manager.is_cancelled(task_id)


def _compute_source_text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _compute_ontology_hash(ontology: dict[str, Any]) -> str:
    canonical = json.dumps(ontology or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _merge_string_lists(base_values: Any, incoming_values: Any) -> list[str]:
    merged: list[str] = []
    seen = set()
    for value in list(base_values or []) + list(incoming_values or []):
        normalized = str(value or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def _merge_json_list(base_values: Any, incoming_values: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen = set()
    for value in list(base_values or []) + list(incoming_values or []):
        if not isinstance(value, dict):
            continue
        key = _canonical_json(value)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(value))
    return merged


def _merge_source_targets(base_values: Any, incoming_values: Any) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen = set()
    for value in list(base_values or []) + list(incoming_values or []):
        if not isinstance(value, dict):
            continue
        source = str(value.get("source") or "").strip()
        target = str(value.get("target") or "").strip()
        if not source or not target:
            continue
        key = (source.lower(), target.lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append({"source": source, "target": target})
    return merged


def _merge_ontology_payload(base_ontology: dict[str, Any], incoming_ontology: dict[str, Any]) -> dict[str, Any]:
    base_entity_types = list((base_ontology or {}).get("entity_types") or [])
    incoming_entity_types = list((incoming_ontology or {}).get("entity_types") or [])
    base_edge_types = list((base_ontology or {}).get("edge_types") or [])
    incoming_edge_types = list((incoming_ontology or {}).get("edge_types") or [])

    def _merge_type_list(base_items: list[Any], incoming_items: list[Any], *, is_relationship: bool) -> list[dict[str, Any]]:
        merged_by_name: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for raw_item in base_items + incoming_items:
            if not isinstance(raw_item, dict):
                continue
            name = _normalize_ontology_type_name(raw_item.get("name"))
            if not name:
                continue
            key = name.lower()
            existing = merged_by_name.get(key)
            if existing is None:
                merged_by_name[key] = {
                    "name": name,
                    "description": str(raw_item.get("description") or "").strip(),
                    "attributes": _merge_json_list(raw_item.get("attributes"), []),
                    "examples": _merge_string_lists(raw_item.get("examples"), []) if not is_relationship else [],
                    "source_targets": _merge_source_targets(raw_item.get("source_targets"), [])
                    if is_relationship
                    else [],
                }
                order.append(key)
                continue
            if not existing.get("description"):
                existing["description"] = str(raw_item.get("description") or "").strip()
            existing["attributes"] = _merge_json_list(existing.get("attributes"), raw_item.get("attributes"))
            if is_relationship:
                existing["source_targets"] = _merge_source_targets(
                    existing.get("source_targets"),
                    raw_item.get("source_targets"),
                )
            else:
                existing["examples"] = _merge_string_lists(existing.get("examples"), raw_item.get("examples"))

        output: list[dict[str, Any]] = []
        for key in order:
            item = merged_by_name[key]
            if is_relationship:
                output.append(
                    {
                        "name": item["name"],
                        "description": item.get("description", ""),
                        "attributes": item.get("attributes", []),
                        "source_targets": item.get("source_targets", []),
                    }
                )
            else:
                output.append(
                    {
                        "name": item["name"],
                        "description": item.get("description", ""),
                        "attributes": item.get("attributes", []),
                        "examples": item.get("examples", []),
                    }
                )
        return output

    return {
        "entity_types": _merge_type_list(base_entity_types, incoming_entity_types, is_relationship=False),
        "edge_types": _merge_type_list(base_edge_types, incoming_edge_types, is_relationship=True),
    }


def _create_ontology_version_if_possible(
    *,
    project_id: str,
    ontology: dict[str, Any],
    source: str,
    parent_version_ids: list[int] | None = None,
    created_by_task_id: str | None = None,
) -> int | None:
    if not ProjectManager._use_postgres_storage():
        return None
    connection_string = ProjectManager._get_storage_connection_string()
    ontology_hash = _compute_ontology_hash(ontology)
    row = insert_ontology_version_data(
        connection_string,
        project_id=project_id,
        source=source,
        ontology_json=ontology,
        ontology_hash=ontology_hash,
        parent_version_ids=parent_version_ids,
        created_by_task_id=created_by_task_id,
    )
    return int(row.get("id")) if row.get("id") is not None else None


def _get_latest_ontology_version_id(project_id: str) -> int | None:
    if not ProjectManager._use_postgres_storage():
        return None
    connection_string = ProjectManager._get_storage_connection_string()
    latest = get_latest_ontology_version_data(connection_string, project_id=project_id)
    if not latest:
        return None
    return int(latest["id"])


def _build_graph_identity_key(
    *,
    project_id: str,
    graph_backend: str,
    chunk_mode: str,
    chunk_size: int,
    chunk_overlap: int,
    source_text_hash: str,
    ontology_hash: str,
) -> str:
    raw = "|".join(
        [
            str(project_id or "").strip(),
            str(graph_backend or "").strip().lower(),
            str(chunk_mode or "").strip().lower(),
            str(int(chunk_size)),
            str(int(chunk_overlap)),
            str(source_text_hash or "").strip(),
            str(ontology_hash or "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_chunk_params_for_mode(
    *,
    chunk_mode: str,
    chunk_size_value: Any,
    chunk_overlap_value: Any,
) -> tuple[int, int]:
    if chunk_mode == CHUNK_MODE_LLAMA_INDEX:
        # LlamaIndex semantic splitting is not driven by fixed size/overlap knobs.
        return -1, -1
    chunk_size = int(chunk_size_value)
    chunk_overlap = int(chunk_overlap_value)
    return chunk_size, chunk_overlap


def _resolve_graph_build_batch_size(request_value: Any) -> int:
    default = max(1, int(Config.GRAPH_BUILD_BATCH_SIZE))
    if request_value is None:
        return default
    try:
        parsed = int(request_value)
    except (TypeError, ValueError):
        return default
    if parsed < 1:
        return default
    return parsed


def _build_project_response_data(project: Any) -> dict[str, Any]:
    project_data = project.to_dict()
    latest_ontology_version_id = _get_latest_ontology_version_id(project_data.get("project_id"))
    if latest_ontology_version_id is not None:
        project_data["ontology_version_id"] = latest_ontology_version_id
    project_data["prompt_label_info"] = PromptLabelManager.get_project_label_info(
        label_name=project_data.get("prompt_label"),
        project_id=project_data.get("project_id"),
        label_id=project_data.get("prompt_label_id"),
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
    if project.status == ProjectStatus.GRAPH_BUILDING:
        task_manager = TaskManager()
        build_tid = str(getattr(project, "graph_build_task_id", "") or "").strip()
        if not task_manager.graph_build_task_is_active(build_tid):
            logger.info(
                "Clearing stale graph_building for project=%s during /project load (task_id=%s inactive)",
                project_id,
                build_tid or "-",
            )
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_build_task_id = None
            project.error = None
            ProjectManager.save_project(project)
            if ProjectManager._use_postgres_storage():
                try:
                    merge_project_data_json_fields(
                        ProjectManager._get_storage_connection_string(),
                        project_id=project_id,
                        fields={
                            "status": ProjectStatus.ONTOLOGY_GENERATED.value,
                            "graph_build_task_id": None,
                            "error": None,
                        },
                    )
                except Exception:
                    logger.exception(
                        "merge_project_data_json_fields after stale graph_building recovery on /project failed project_id=%s",
                        project_id,
                    )
    return {
        "success": True,
        "data": _build_project_response_data(project),
    }


@router.get("/project/{project_id}/graph-build/resume-candidate")
def get_graph_build_resume_candidate(project_id: str) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")

    if not ProjectManager._use_postgres_storage():
        return {"success": True, "data": None}

    connection_string = ProjectManager._get_storage_connection_string()
    if not connection_string:
        return {"success": True, "data": None}

    candidate = get_latest_graph_build_resume_candidate(
        connection_string,
        project_id=project_id,
    )
    if not candidate:
        return {"success": True, "data": None}

    return {
        "success": True,
        "data": {
            "task_id": candidate.get("task_id"),
            "status": candidate.get("status"),
            "total_batches": candidate.get("total_batches"),
            "last_completed_batch_index": candidate.get("last_completed_batch_index"),
            "batch_size": candidate.get("batch_size"),
            "resume_state": candidate.get("resume_state"),
            "updated_at": candidate.get("updated_at"),
        },
    }


@router.get("/project/{project_id}/ontology-versions")
def list_project_ontology_versions(project_id: str, limit: int = Query(default=30, ge=1, le=200)) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")
    if not ProjectManager._use_postgres_storage():
        return {
            "success": True,
            "data": [],
            "count": 0,
        }
    rows = list_ontology_versions_data(
        ProjectManager._get_storage_connection_string(),
        project_id=project_id,
        limit=limit,
    )
    return {
        "success": True,
        "data": rows,
        "count": len(rows),
    }


@router.post("/project/{project_id}/ontology/merge")
def merge_project_ontology(project_id: str, data: ProjectPatchBody) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")
    incoming_ontology_raw = (data or {}).get("incoming_ontology")
    if incoming_ontology_raw is None:
        return _error_response(400, "incoming_ontology is required")
    try:
        incoming_ontology = _sanitize_ontology_payload(incoming_ontology_raw)
        base_ontology = _sanitize_ontology_payload((data or {}).get("base_ontology") or project.ontology or {})
    except ValueError as exc:
        return _error_response(400, str(exc))

    merged_ontology = _merge_ontology_payload(base_ontology, incoming_ontology)
    parent_version_ids: list[int] = []
    latest_id = _get_latest_ontology_version_id(project.project_id)
    if latest_id is not None:
        parent_version_ids.append(latest_id)

    project.ontology = merged_ontology
    project.error = None
    preserve_graph_status = _coerce_bool((data or {}).get("preserve_graph_status", True))
    if not preserve_graph_status:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        project.zep_graph_id = None
        project.project_workspace_id = None
        project.zep_graph_address = None
        project.graph_build_task_id = None
    ProjectManager.save_project(project)
    new_version_id = _create_ontology_version_if_possible(
        project_id=project.project_id,
        ontology=merged_ontology,
        source="merged",
        parent_version_ids=parent_version_ids or None,
    )
    return {
        "success": True,
        "message": f"Ontology merged for project: {project_id}",
        "data": {
            "project_id": project.project_id,
            "ontology": merged_ontology,
            "ontology_version_id": new_version_id,
        },
    }


@router.patch("/project/{project_id}")
def update_project(project_id: str, data: ProjectPatchBody) -> Any:
    project = ProjectManager.get_project(project_id)
    if not project:
        return _error_response(404, f"Project not found: {project_id}")

    name = str((data or {}).get("name", "")).strip()
    prompt_label = str((data or {}).get("prompt_label", "")).strip()
    raw_ontology = (data or {}).get("ontology")
    raw_refresh_data_while_build = (data or {}).get("refresh_data_while_build")
    has_refresh_data_while_build = raw_refresh_data_while_build is not None
    preserve_graph_status = _coerce_bool((data or {}).get("preserve_graph_status"))
    has_ontology = raw_ontology is not None
    if not name and not prompt_label and not has_ontology and not has_refresh_data_while_build:
        return _error_response(
            400,
            "At least one field is required: name, prompt_label, ontology, or refresh_data_while_build",
        )

    if name:
        project.name = name
    if prompt_label:
        label = PromptLabelManager.create_label(prompt_label)
        project.prompt_label = str(label.get("name") or prompt_label)
        project.prompt_label_id = (
            int(label["id"]) if label.get("id") is not None else None
        )
    if has_refresh_data_while_build:
        project.refresh_data_while_build = _coerce_bool(raw_refresh_data_while_build)
    if has_ontology:
        existing_graph_id = str(getattr(project, "zep_graph_id", "") or "").strip()
        original_ontology_version_id = _get_latest_ontology_version_id(project.project_id)
        try:
            project.ontology = _sanitize_ontology_payload(raw_ontology)
        except ValueError as exc:
            return _error_response(400, str(exc))

        if not preserve_graph_status:
            # Ontology edits require rebuilding graph with the updated schema.
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.zep_graph_id = None
            project.project_workspace_id = None
            project.zep_graph_address = None
            project.graph_build_task_id = None
            project.error = None
        latest_ontology_version_id = _create_ontology_version_if_possible(
            project_id=project.project_id,
            ontology=project.ontology,
            source="merged" if preserve_graph_status else "manual",
            parent_version_ids=[original_ontology_version_id] if original_ontology_version_id else None,
        )
    else:
        latest_ontology_version_id = None

    ProjectManager.save_project(project)
    response_data = _build_project_response_data(project)
    if latest_ontology_version_id is not None:
        response_data["ontology_version_id"] = latest_ontology_version_id
    return {
        "success": True,
        "message": f"Project updated: {project_id}",
        "data": response_data,
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
    pdf_page_from: int | None = Form(None),
    pdf_page_to: int | None = Form(None),
) -> Any:
    try:
        normalized_project_id = str(project_id or "").strip()
        normalized_project_name = str(project_name or "").strip() or "Unnamed Project"
        normalized_graph_backend = _normalize_graph_backend(graph_backend)
        normalized_prompt_label = str(prompt_label or "").strip() or "Production"
        normalized_pdf_page_from = _normalize_pdf_page(
            pdf_page_from,
            field_name="pdf_page_from",
            default=None,
        )
        normalized_pdf_page_to = _normalize_pdf_page(
            pdf_page_to,
            field_name="pdf_page_to",
            default=None,
        )
        if (
            normalized_pdf_page_from is not None
            and normalized_pdf_page_to is not None
            and normalized_pdf_page_from > normalized_pdf_page_to
        ):
            normalized_pdf_page_from, normalized_pdf_page_to = (
                normalized_pdf_page_to,
                normalized_pdf_page_from,
            )

        if normalized_project_id:
            project = ProjectManager.get_project(normalized_project_id)
            if not project:
                return _error_response(404, f"Project not found: {normalized_project_id}")
            created_new_project = False
        else:
            project = ProjectManager.create_project(name=normalized_project_name, persist=False)
            created_new_project = True

        project.name = normalized_project_name
        label = PromptLabelManager.create_label(normalized_prompt_label)
        project.prompt_label = str(label.get("name") or normalized_prompt_label)
        project.prompt_label_id = int(label["id"]) if label.get("id") is not None else None
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
                extracted_text = FileParser.extract_text(
                    file_info["path"],
                    pdf_page_from=normalized_pdf_page_from,
                    pdf_page_to=normalized_pdf_page_to,
                )
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

        task_manager = TaskManager()
        if project.status == ProjectStatus.GRAPH_BUILDING:
            build_tid = str(getattr(project, "graph_build_task_id", "") or "").strip()
            if not task_manager.graph_build_task_is_active(build_tid):
                logger.info(
                    "Clearing stale graph_building for project=%s (task_id=%s not active in this process)",
                    project_id,
                    build_tid or "-",
                )
                project.status = ProjectStatus.ONTOLOGY_GENERATED
                project.graph_build_task_id = None
                project.error = None
                ProjectManager.save_project(project)
                if ProjectManager._use_postgres_storage():
                    try:
                        merge_project_data_json_fields(
                            ProjectManager._get_storage_connection_string(),
                            project_id=project_id,
                            fields={
                                "status": ProjectStatus.ONTOLOGY_GENERATED.value,
                                "graph_build_task_id": None,
                                "error": None,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "merge_project_data_json_fields after stale graph_building recovery failed project_id=%s",
                            project_id,
                        )

        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Graph is building, force rebuild use `force: true`",
                    "task_id": project.graph_build_task_id,
                },
            )

        did_force_reset = False
        if force and project.status in {
            ProjectStatus.GRAPH_BUILDING,
            ProjectStatus.FAILED,
            ProjectStatus.GRAPH_COMPLETED,
        }:
            did_force_reset = True
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.zep_graph_id = None
            project.project_workspace_id = None
            project.zep_graph_address = None
            project.graph_build_task_id = None
            project.error = None

        if did_force_reset:
            ProjectManager.save_project(project)
            if ProjectManager._use_postgres_storage():
                try:
                    merge_project_data_json_fields(
                        ProjectManager._get_storage_connection_string(),
                        project_id=project_id,
                        fields={
                            "status": ProjectStatus.ONTOLOGY_GENERATED.value,
                            "graph_build_task_id": None,
                            "zep_graph_id": None,
                            "project_workspace_id": None,
                            "zep_graph_address": None,
                            "error": None,
                        },
                    )
                except Exception:
                    logger.exception(
                        "merge_project_data_json_fields after force reset failed project_id=%s",
                        project_id,
                    )

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
            project_name_graph_id = _build_project_name_graph_id(project.name)
            if not project_name_graph_id:
                return _error_response(
                    400,
                    "project name cannot be converted to a valid graph id",
                )

        resolved_graph_id = project_name_graph_id or requested_graph_id or existing_graph_id or None

        graph_name = data.get("graph_name", project.name or "imp Graph")
        graph_label = str(data.get("graph_label") or "").strip() or None
        override_graph = (
            _coerce_bool(data.get("override"))
            or _coerce_bool(data.get("overwrite"))
            or _coerce_bool(data.get("override_graph"))
        )
        raw_enable_otel_tracing = data.get("enable_otel_tracing")
        request_enable_otel_tracing = (
            _coerce_bool(raw_enable_otel_tracing) if raw_enable_otel_tracing is not None else None
        )
        project_enable_otel_tracing = getattr(project, "enable_otel_tracing", None)
        if not isinstance(project_enable_otel_tracing, bool):
            project_enable_otel_tracing = None
        enable_otel_tracing = (
            request_enable_otel_tracing
            if request_enable_otel_tracing is not None
            else (
                project_enable_otel_tracing
                if project_enable_otel_tracing is not None
                else Config.APPLY_LANGFUSE_TO_GRAPHITI_TRACE
            )
        )
        raw_enable_oracle_runtime_overrides = data.get("enable_oracle_runtime_overrides")
        if raw_enable_oracle_runtime_overrides is not None:
            enable_oracle_runtime_overrides = _coerce_bool(raw_enable_oracle_runtime_overrides)
        else:
            enable_oracle_runtime_overrides = bool(
                getattr(project, "enable_oracle_runtime_overrides", True)
            )

        if enable_oracle_runtime_overrides:
            existing_oracle_runtime = _resolve_oracle_runtime_settings(project, use_project_overrides=True)
            request_oracle_pool_min = _coerce_optional_positive_int(data.get("oracle_pool_min"))
            request_oracle_pool_max = _coerce_optional_positive_int(data.get("oracle_pool_max"))
            request_oracle_pool_increment = _coerce_optional_positive_int(data.get("oracle_pool_increment"))
            request_oracle_max_coroutines = _coerce_optional_positive_int(data.get("oracle_max_coroutines"))
            oracle_pool_min = (
                request_oracle_pool_min
                if "oracle_pool_min" in data
                else existing_oracle_runtime["oracle_pool_min"]
            )
            oracle_pool_max = (
                request_oracle_pool_max
                if "oracle_pool_max" in data
                else existing_oracle_runtime["oracle_pool_max"]
            )
            oracle_pool_increment = (
                request_oracle_pool_increment
                if "oracle_pool_increment" in data
                else existing_oracle_runtime["oracle_pool_increment"]
            )
            oracle_max_coroutines = (
                request_oracle_max_coroutines
                if "oracle_max_coroutines" in data
                else existing_oracle_runtime["oracle_max_coroutines"]
            )
        else:
            global_oracle_runtime = _resolve_oracle_runtime_settings(
                project,
                use_project_overrides=False,
            )
            oracle_pool_min = global_oracle_runtime["oracle_pool_min"]
            oracle_pool_max = global_oracle_runtime["oracle_pool_max"]
            oracle_pool_increment = global_oracle_runtime["oracle_pool_increment"]
            oracle_max_coroutines = global_oracle_runtime["oracle_max_coroutines"]
        chunk_mode = normalize_chunk_mode(data.get("chunk_mode", getattr(project, "chunk_mode", None)))
        if chunk_mode not in SUPPORTED_CHUNK_MODES:
            chunk_mode = CHUNK_MODE_FIXED
        chunk_size, chunk_overlap = _resolve_chunk_params_for_mode(
            chunk_mode=chunk_mode,
            chunk_size_value=data.get("chunk_size", project.chunk_size or DEFAULT_CHUNK_SIZE),
            chunk_overlap_value=data.get("chunk_overlap", project.chunk_overlap or DEFAULT_CHUNK_OVERLAP),
        )
        graphiti_embedding_model = _resolve_graphiti_embedding_model(
            data.get("graphiti_embedding_model"),
            getattr(project, "graphiti_embedding_model", None),
        )

        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        project.chunk_mode = chunk_mode
        project.graph_backend = resolved_graph_backend
        project.graphiti_embedding_model = graphiti_embedding_model
        project.enable_otel_tracing = enable_otel_tracing
        project.enable_oracle_runtime_overrides = enable_oracle_runtime_overrides
        if enable_oracle_runtime_overrides:
            project.oracle_pool_min = oracle_pool_min
            project.oracle_pool_max = oracle_pool_max
            project.oracle_pool_increment = oracle_pool_increment
            project.oracle_max_coroutines = oracle_max_coroutines

        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return _error_response(400, "no extracted text")

        ontology = project.ontology
        if not ontology:
            return _error_response(400, "no ontology")

        source_text_hash = _compute_source_text_hash(text)
        ontology_hash = _compute_ontology_hash(ontology)
        ontology_version_id = _get_latest_ontology_version_id(project_id)
        if ontology_version_id is None:
            ontology_version_id = _create_ontology_version_if_possible(
                project_id=project_id,
                ontology=ontology,
                source="original",
            )
        build_identity_key = _build_graph_identity_key(
            project_id=project_id,
            graph_backend=resolved_graph_backend,
            chunk_mode=chunk_mode,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            source_text_hash=source_text_hash,
            ontology_hash=ontology_hash,
        )
        batch_size = _resolve_graph_build_batch_size(data.get("batch_size"))

        task_id = task_manager.create_task(
            "graph_build",
            metadata={
                "project_id": project_id,
                "graph_name": graph_name,
                "graph_label": graph_label,
                "graph_backend": resolved_graph_backend,
                "chunk_mode": chunk_mode,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "batch_size": batch_size,
                "override_graph": override_graph,
                "enable_otel_tracing": enable_otel_tracing,
                "enable_oracle_runtime_overrides": enable_oracle_runtime_overrides,
                "oracle_pool_min": oracle_pool_min,
                "oracle_pool_max": oracle_pool_max,
                "oracle_pool_increment": oracle_pool_increment,
                "oracle_max_coroutines": oracle_max_coroutines,
                "graphiti_embedding_model": graphiti_embedding_model,
                "source_text_hash": source_text_hash,
                "ontology_hash": ontology_hash,
                "ontology_version_id": ontology_version_id,
                "build_identity_key": build_identity_key,
            },
        )
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
        if ProjectManager._use_postgres_storage():
            try:
                merge_project_data_json_fields(
                    ProjectManager._get_storage_connection_string(),
                    project_id=project_id,
                    fields={
                        "graph_build_task_id": task_id,
                        "status": ProjectStatus.GRAPH_BUILDING.value,
                    },
                )
            except Exception:
                logger.exception(
                    "merge_project_data_json_fields after new graph_build task failed project_id=%s task_id=%s",
                    project_id,
                    task_id,
                )
        batch_manager = BatchProcessManager()

        def build_task() -> None:
            build_logger = get_logger("z_graph.build")
            try:
                build_logger.info(f"[{task_id}] Start building graph")
                build_logger.info(
                    "[%s] Using backend=%s graph_backend=%s project_id=%s build_identity=%s otel_tracing=%s",
                    task_id,
                    client_backend,
                    resolved_graph_backend,
                    project_id,
                    build_identity_key,
                    enable_otel_tracing,
                )

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    message="Initializing graph build service",
                )
                if _is_task_cancelled(task_manager, task_id):
                    raise TaskCancelledError("Task cancelled before graph build initialization")

                builder = GraphBuilderService(
                    backend=client_backend,
                    graph_backend=resolved_graph_backend,
                    graphiti_embedding_model=graphiti_embedding_model,
                    api_key=Config.ZEP_API_KEY,
                    project_id=str(project_id or "").strip() or None,
                    enable_otel_tracing=enable_otel_tracing,
                    oracle_pool_min=oracle_pool_min if resolved_graph_backend == GRAPH_BACKEND_ORACLE else None,
                    oracle_pool_max=oracle_pool_max if resolved_graph_backend == GRAPH_BACKEND_ORACLE else None,
                    oracle_pool_increment=oracle_pool_increment
                    if resolved_graph_backend == GRAPH_BACKEND_ORACLE
                    else None,
                    oracle_max_coroutines=oracle_max_coroutines
                    if resolved_graph_backend == GRAPH_BACKEND_ORACLE
                    else None,
                    client_profile="build_graph",
                )

                if override_graph and resolved_graph_id:
                    task_manager.update_task(
                        task_id,
                        message=f"Override enabled: deleting graph '{resolved_graph_id}' first",
                        progress=3,
                    )
                    try:
                        builder.delete_graph(resolved_graph_id)
                        build_logger.info(
                            "[%s] Override delete completed: graph_id=%s",
                            task_id,
                            resolved_graph_id,
                        )
                    except Exception as delete_exc:
                        if _looks_like_missing_graph_error(delete_exc):
                            build_logger.info(
                                "[%s] Override delete skipped, graph not found: graph_id=%s",
                                task_id,
                                resolved_graph_id,
                            )
                        else:
                            raise

                task_manager.update_task(
                    task_id,
                    message=f"Splitting Text ({chunk_mode} mode)",
                    progress=5,
                )
                if _is_task_cancelled(task_manager, task_id):
                    raise TaskCancelledError("Task cancelled before chunk splitting")

                split_chunk_size = chunk_size if chunk_size > 0 else DEFAULT_CHUNK_SIZE
                split_chunk_overlap = chunk_overlap if chunk_overlap >= 0 else 0
                chunks = split_text_with_mode(
                    text,
                    chunk_size=split_chunk_size,
                    overlap=split_chunk_overlap,
                    chunk_mode=chunk_mode,
                )
                total_chunks = len(chunks)
                total_batches = (total_chunks + batch_size - 1) // batch_size if total_chunks > 0 else 0

                resume_context = batch_manager.resolve_resume_context(
                    project_id=project_id,
                    build_identity_key=build_identity_key,
                    current_task_id=task_id,
                    override_graph=override_graph,
                    total_batches=total_batches,
                )
                run_graph_id = (
                    str(resume_context.matched_graph_id or "").strip()
                    or str(resolved_graph_id or "").strip()
                    or None
                )
                build_logger.info(
                    "[%s] build_identity=%s source_text_hash=%s ontology_hash=%s decision=%s start_batch=%s/%s previous_task_id=%s",
                    task_id,
                    build_identity_key,
                    source_text_hash,
                    ontology_hash,
                    resume_context.resume_state,
                    resume_context.start_batch_index,
                    total_batches,
                    resume_context.matched_task_id or "-",
                )
                task_manager.update_task(
                    task_id,
                    progress_detail={
                        "build_identity_key": build_identity_key,
                        "source_text_hash": source_text_hash,
                        "ontology_hash": ontology_hash,
                        "ontology_version_id": ontology_version_id,
                        "resume_state": resume_context.resume_state,
                        "matched_task_id": resume_context.matched_task_id or "",
                        "last_completed_batch_index": max(-1, resume_context.start_batch_index - 1),
                        "total_batches": total_batches,
                        "total_chunks": total_chunks,
                        "batch_size": batch_size,
                    },
                )

                backend_display_name = _graph_backend_display_name(resolved_graph_backend)
                task_manager.update_task(
                    task_id,
                    message=f"Creating {backend_display_name} graph",
                    progress=10,
                )
                if _is_task_cancelled(task_manager, task_id):
                    raise TaskCancelledError("Task cancelled before graph creation")
                graph_id, project_workspace_id = builder.create_graph(
                    name=graph_name,
                    project_id=project_id,
                    graph_id=run_graph_id,
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

                task_manager.update_task(
                    task_id,
                    message="Setting Ontology",
                    progress=15,
                    progress_detail={
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "zep_graph_id": graph_id,
                        "graph_label": graph_label or "",
                        "project_workspace_id": project_workspace_id or "",
                        "zep_graph_address": project.zep_graph_address or "",
                        "graph_backend": resolved_graph_backend,
                        "graphiti_embedding_model": graphiti_embedding_model,
                        "graph_label": graph_label or "",
                        "build_identity_key": build_identity_key,
                        "source_text_hash": source_text_hash,
                        "ontology_hash": ontology_hash,
                        "ontology_version_id": ontology_version_id,
                    },
                )
                builder.set_ontology(graph_id, ontology)
                if _is_task_cancelled(task_manager, task_id):
                    raise TaskCancelledError("Task cancelled after ontology setup")

                def add_progress_callback(message: str, progress_ratio: float) -> None:
                    progress = 15 + int(progress_ratio * 40)
                    task_manager.update_task(task_id, message=message, progress=progress)

                def checkpoint_callback(batch_index: int, batch_count: int) -> None:
                    checkpoint_payload = {
                        "resume_state": resume_context.resume_state,
                        "last_completed_batch_index": batch_index,
                        "total_batches": batch_count,
                        "total_chunks": total_chunks,
                        "batch_size": batch_size,
                    }
                    task_manager.update_task(task_id, progress_detail=checkpoint_payload)
                    batch_manager.persist_checkpoint(
                        task_id=task_id,
                        batch_index=batch_index,
                        total_batches=batch_count,
                        total_chunks=total_chunks,
                        batch_size=batch_size,
                        resume_state=resume_context.resume_state,
                    )

                if resume_context.start_batch_index > 0:
                    task_manager.update_task(
                        task_id,
                        message=(
                            f"Resuming build from batch {resume_context.start_batch_index + 1}/{total_batches}"
                        ),
                        progress=20,
                    )
                else:
                    task_manager.update_task(
                        task_id,
                        message=f"Adding {total_chunks} chunks",
                        progress=15,
                    )

                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=batch_size,
                    progress_callback=add_progress_callback,
                    checkpoint_callback=checkpoint_callback,
                    start_batch_index=resume_context.start_batch_index,
                    should_stop=lambda: _is_task_cancelled(task_manager, task_id),
                )

                task_manager.update_task(
                    task_id,
                    message=f"Waiting for {backend_display_name} to process data",
                    progress=45,
                )

                def wait_progress_callback(message: str, progress_ratio: float) -> None:
                    progress = 55 + int(progress_ratio * 35)
                    task_manager.update_task(task_id, message=message, progress=progress)

                builder._wait_for_episodes(
                    episode_uuids,
                    wait_progress_callback,
                    should_stop=lambda: _is_task_cancelled(task_manager, task_id),
                )
                if _is_task_cancelled(task_manager, task_id):
                    raise TaskCancelledError("Task cancelled before graph data fetch")

                task_manager.update_task(task_id, message="Getting Graph Data", progress=90)
                graph_data = builder.get_graph_data(graph_id, include_episode_data=False)
                if _is_task_cancelled(task_manager, task_id):
                    raise TaskCancelledError("Task cancelled before completion")

                project.status = ProjectStatus.GRAPH_COMPLETED
                project.has_built_graph = True
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
                    "[%s] Graph Build Completed: graph_id=%s, nodes=%s, edges=%s",
                    task_id,
                    graph_id,
                    node_count,
                    edge_count,
                )

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="Graph Build Completed",
                    progress=100,
                    progress_detail={
                        "resume_state": "completed",
                        "last_completed_batch_index": max(-1, total_batches - 1),
                        "total_batches": total_batches,
                        "total_chunks": total_chunks,
                        "batch_size": batch_size,
                    },
                    result={
                        "project_id": project_id,
                        "zep_graph_id": graph_id,
                        "graph_backend": resolved_graph_backend,
                        "graphiti_embedding_model": graphiti_embedding_model,
                        "graph_label": graph_label or "",
                        "chunk_mode": chunk_mode,
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                        "source_text_hash": source_text_hash,
                        "ontology_hash": ontology_hash,
                        "ontology_version_id": ontology_version_id,
                        "build_identity_key": build_identity_key,
                        "batch_size": batch_size,
                        "total_chunks": total_chunks,
                        "total_batches": total_batches,
                        "last_completed_batch_index": max(-1, total_batches - 1),
                        "resume_state": "completed",
                        "project_workspace_id": project_workspace_id,
                        "zep_graph_address": project.zep_graph_address,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks,
                    },
                )
            except TaskCancelledError:
                build_logger.info("[%s] Graph Build Cancelled", task_id)
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.CANCELLED,
                    message="Graph build cancelled by user",
                    progress_detail={"resume_state": "cancelled"},
                )
                project.status = ProjectStatus.ONTOLOGY_GENERATED
                project.graph_build_task_id = None
                project.error = None
                _timed_task_call(
                    task_manager,
                    task_id,
                    "step_b",
                    "ProjectManager.save_project",
                    ProjectManager.save_project,
                    project,
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
                    progress_detail={"resume_state": "failed"},
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


@router.post("/task/{task_id}/cancel")
def cancel_task(task_id: str) -> Any:
    task_manager = TaskManager()
    task = task_manager.get_task(task_id)
    if not task:
        return _error_response(404, f"Task not found: {task_id}")
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
        return {
            "success": True,
            "message": f"Task already finished: {task.status.value}",
            "data": task.to_dict(),
        }

    cancelled = task_manager.cancel_task(task_id, message="Task cancellation requested by user")
    updated_task = task_manager.get_task(task_id)
    if not cancelled or not updated_task:
        return _error_response(400, f"Task cannot be cancelled: {task_id}")
    return {
        "success": True,
        "message": f"Task cancellation requested: {task_id}",
        "data": updated_task.to_dict(),
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
        resolved_project = None
        project_graph_backend = ""
        if normalized_project_id:
            resolved_project = ProjectManager.get_project(normalized_project_id)
            if resolved_project is not None:
                project_graph_backend = str(getattr(resolved_project, "graph_backend", "") or "")

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
        oracle_project_error = _require_project_id_for_oracle_backend(
            resolved_graph_backend,
            normalized_project_id,
            route_name="/api/data/{graph_id}",
        )
        if oracle_project_error is not None:
            return oracle_project_error

        def _load_graph_data(selected_backend: str, selected_graph_backend: str) -> dict[str, Any]:
            oracle_runtime = (
                _resolve_oracle_runtime_settings(resolved_project)
                if selected_graph_backend == GRAPH_BACKEND_ORACLE and resolved_project is not None
                else None
            )
            cached_client = get_or_create_zep_client(
                backend=selected_backend,
                api_key=Config.ZEP_API_KEY,
                graph_backend=selected_graph_backend,
                project_id=normalized_project_id or None,
                oracle_pool_min=oracle_runtime["oracle_pool_min"] if oracle_runtime is not None else None,
                oracle_pool_max=oracle_runtime["oracle_pool_max"] if oracle_runtime is not None else None,
                oracle_pool_increment=oracle_runtime["oracle_pool_increment"]
                if oracle_runtime is not None
                else None,
                oracle_max_coroutines=oracle_runtime["oracle_max_coroutines"]
                if oracle_runtime is not None
                else None,
                client_profile="non_build_graph",
            )
            builder = GraphBuilderService(
                client=cached_client,
                backend=selected_backend,
                graph_backend=selected_graph_backend,
                api_key=Config.ZEP_API_KEY,
                project_id=normalized_project_id or None,
                oracle_pool_min=oracle_runtime["oracle_pool_min"] if oracle_runtime is not None else None,
                oracle_pool_max=oracle_runtime["oracle_pool_max"] if oracle_runtime is not None else None,
                oracle_pool_increment=oracle_runtime["oracle_pool_increment"]
                if oracle_runtime is not None
                else None,
                oracle_max_coroutines=oracle_runtime["oracle_max_coroutines"]
                if oracle_runtime is not None
                else None,
                client_profile="non_build_graph",
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


@router.get("/graph/search")
def search_graph_data(
    graph_id: str = Query(...),
    query: str = Query(...),
    scope: str = Query(default="all"),
    limit: int = Query(default=24, ge=1, le=100),
    graph_backend: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
) -> Any:
    try:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return {"success": True, "data": {"nodes": [], "edges": [], "episodes": []}}

        normalized_project_id = str(project_id or "").strip()
        resolved_project = None
        project_graph_backend = ""
        if normalized_project_id:
            resolved_project = ProjectManager.get_project(normalized_project_id)
            if resolved_project is not None:
                project_graph_backend = str(getattr(resolved_project, "graph_backend", "") or "")

        requested_graph_backend = _normalize_graph_backend(graph_backend)
        resolved_graph_backend = _resolve_graph_backend(project_graph_backend, requested_graph_backend)
        oracle_project_error = _require_project_id_for_oracle_backend(
            resolved_graph_backend,
            normalized_project_id,
            route_name="/api/graph/search",
        )
        if oracle_project_error is not None:
            return oracle_project_error

        normalized_scope = _normalize_graph_search_scope(scope)
        client_scope = "both"
        if normalized_scope == "node":
            client_scope = "nodes"
        elif normalized_scope == "edge":
            client_scope = "edges"
        elif normalized_scope == "episode":
            client_scope = "edges"

        oracle_runtime = (
            _resolve_oracle_runtime_settings(resolved_project)
            if resolved_graph_backend == GRAPH_BACKEND_ORACLE and resolved_project is not None
            else None
        )
        selected_backend = _client_backend_for_graph_backend(resolved_graph_backend)
        cached_client = get_or_create_zep_client(
            backend=selected_backend,
            api_key=Config.ZEP_API_KEY,
            graph_backend=resolved_graph_backend,
            project_id=normalized_project_id or None,
            oracle_pool_min=oracle_runtime["oracle_pool_min"] if oracle_runtime is not None else None,
            oracle_pool_max=oracle_runtime["oracle_pool_max"] if oracle_runtime is not None else None,
            oracle_pool_increment=oracle_runtime["oracle_pool_increment"] if oracle_runtime is not None else None,
            oracle_max_coroutines=oracle_runtime["oracle_max_coroutines"] if oracle_runtime is not None else None,
            client_profile="non_build_graph",
        )
        builder = GraphBuilderService(
            client=cached_client,
            backend=selected_backend,
            graph_backend=resolved_graph_backend,
            api_key=Config.ZEP_API_KEY,
            project_id=normalized_project_id or None,
            oracle_pool_min=oracle_runtime["oracle_pool_min"] if oracle_runtime is not None else None,
            oracle_pool_max=oracle_runtime["oracle_pool_max"] if oracle_runtime is not None else None,
            oracle_pool_increment=oracle_runtime["oracle_pool_increment"] if oracle_runtime is not None else None,
            oracle_max_coroutines=oracle_runtime["oracle_max_coroutines"] if oracle_runtime is not None else None,
            client_profile="non_build_graph",
        )
        search_result = builder.client.search(
            graph_id=graph_id,
            query=normalized_query,
            limit=limit,
            scope=client_scope,
            reranker="cross_encoder",
        )
        nodes = list(getattr(search_result, "nodes", []) or [])
        edges = list(getattr(search_result, "edges", []) or [])

        nodes_payload: list[dict[str, Any]] = []
        for node in nodes:
            node_uuid = str(getattr(node, "uuid", "") or "").strip()
            if not node_uuid:
                continue
            nodes_payload.append(
                {
                    "uuid": node_uuid,
                    "name": str(getattr(node, "name", "") or ""),
                    "labels": list(getattr(node, "labels", []) or []),
                    "summary": str(getattr(node, "summary", "") or ""),
                    "attributes": getattr(node, "attributes", {}) or {},
                }
            )

        edges_payload: list[dict[str, Any]] = []
        episode_node_anchors: dict[str, set[str]] = {}
        for edge in edges:
            edge_uuid = str(getattr(edge, "uuid", "") or "").strip()
            source_node_uuid = str(getattr(edge, "source_node_uuid", "") or "").strip()
            target_node_uuid = str(getattr(edge, "target_node_uuid", "") or "").strip()
            episodes = list(getattr(edge, "episodes", []) or [])
            episode_ids = [str(episode_id or "").strip() for episode_id in episodes if str(episode_id or "").strip()]
            for episode_id in episode_ids:
                anchor_set = episode_node_anchors.setdefault(episode_id, set())
                if source_node_uuid:
                    anchor_set.add(source_node_uuid)
                if target_node_uuid:
                    anchor_set.add(target_node_uuid)
            edges_payload.append(
                {
                    "uuid": edge_uuid,
                    "name": str(getattr(edge, "name", "") or ""),
                    "fact": str(getattr(edge, "fact", "") or ""),
                    "fact_type": str(getattr(edge, "fact_type", "") or ""),
                    "source_node_uuid": source_node_uuid,
                    "target_node_uuid": target_node_uuid,
                    "episodes": episode_ids,
                }
            )

        include_nodes = normalized_scope in {"all", "node"}
        include_edges = normalized_scope in {"all", "edge"}
        include_episodes = normalized_scope in {"all", "episode"}
        episodes_payload = (
            _collect_episode_search_hits(
                builder=builder,
                query=normalized_query,
                episode_node_anchors=episode_node_anchors,
                episode_limit=limit,
            )
            if include_episodes
            else []
        )

        return {
            "success": True,
            "data": {
                "nodes": nodes_payload if include_nodes else [],
                "edges": edges_payload if include_edges else [],
                "episodes": episodes_payload,
            },
        }
    except Exception as exc:
        logger.exception("Failed to search graph data")
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
        oracle_project_error = _require_project_id_for_oracle_backend(
            resolved_graph_backend,
            normalized_project_id,
            route_name="/api/delete/{graph_id}",
        )
        if oracle_project_error is not None:
            return oracle_project_error

        selected_backend = _client_backend_for_graph_backend(resolved_graph_backend)
        cached_client = get_or_create_zep_client(
            backend=selected_backend,
            api_key=Config.ZEP_API_KEY,
            graph_backend=resolved_graph_backend,
            project_id=normalized_project_id or None,
            client_profile="non_build_graph",
        )
        builder = GraphBuilderService(
            client=cached_client,
            backend=selected_backend,
            graph_backend=resolved_graph_backend,
            api_key=Config.ZEP_API_KEY,
            project_id=normalized_project_id or None,
            client_profile="non_build_graph",
        )
        builder.delete_graph(graph_id)
        return {
            "success": True,
            "message": f"Graph deleted: {graph_id}",
        }
    except Exception as exc:
        logger.exception("Failed to delete graph")
        return _error_response(500, str(exc), exc)
