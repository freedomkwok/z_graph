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

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

_POSTGRES_SCHEMA_INITIALIZED = False
logger = logging.getLogger("z_graph.db_query")


def _connect_postgres(connection_string: str):
    psycopg = import_module("psycopg")
    return psycopg.connect(connection_string)


def _decode_project_data(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    raise ValueError("Invalid project_data payload from storage")


def _derive_has_built_graph(latest_graph_build_status: Any, fallback_value: bool, project_status: Any) -> bool:
    normalized_latest_status = str(latest_graph_build_status or "").strip().lower()
    if normalized_latest_status:
        return normalized_latest_status == "completed"

    if fallback_value:
        return True

    return str(project_status or "").strip().lower() == "graph_completed"


def _build_graph_resume_candidate(
    *,
    latest_graph_build_status: Any,
    total_batches: Any,
    last_completed_batch_index: Any,
    batch_size: Any,
    resume_state: Any,
    updated_at: Any,
    task_id: Any,
) -> dict[str, Any] | None:
    status = str(latest_graph_build_status or "").strip().lower()
    if not status or status == "completed":
        return None
    parsed_total_batches = int(total_batches) if total_batches is not None else None
    if parsed_total_batches is None or parsed_total_batches < 1:
        return None
    parsed_last_idx = int(last_completed_batch_index) if last_completed_batch_index is not None else -1
    parsed_batch_size = int(batch_size) if batch_size is not None else None
    return {
        "task_id": str(task_id or "").strip(),
        "status": status,
        "total_batches": parsed_total_batches,
        "last_completed_batch_index": parsed_last_idx,
        "batch_size": parsed_batch_size,
        "resume_state": str(resume_state or "").strip().lower() or None,
        "updated_at": str(updated_at or ""),
    }


def _load_schema_sql_statements(schema_sql_path: Path) -> list[str]:
    if not schema_sql_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_sql_path}")

    schema_sql = schema_sql_path.read_text(encoding="utf-8")
    statements = [statement.strip() for statement in schema_sql.split(";") if statement.strip()]
    if not statements:
        raise ValueError(f"No SQL statements found in schema: {schema_sql_path}")
    return statements


def ensure_postgres_schema(connection_string: str, schema_sql_path: Path) -> None:
    global _POSTGRES_SCHEMA_INITIALIZED
    if _POSTGRES_SCHEMA_INITIALIZED:
        return

    statements = _load_schema_sql_statements(schema_sql_path)
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()

    _POSTGRES_SCHEMA_INITIALIZED = True


def merge_project_data_json_fields(
    connection_string: str,
    *,
    project_id: str,
    fields: dict[str, Any],
    updated_at: str | None = None,
) -> None:
    """
    Shallow-merge keys into projects.project_data (JSONB) without replacing the whole blob.

    Used to keep graph_build_task_id / status aligned with graph_build rows when the app
    restarts and a new build task_id is issued.
    """
    normalized_id = str(project_id or "").strip()
    if not normalized_id:
        return

    now_iso = str(updated_at or datetime.now().isoformat())
    payload = dict(fields or {})
    payload["updated_at"] = now_iso

    started_at = time.perf_counter()
    affected_rows = 0
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE projects
                SET
                    project_data = COALESCE(project_data, '{}'::jsonb) || %s::jsonb,
                    updated_at = %s
                WHERE project_id = %s
                """,
                (json.dumps(payload, ensure_ascii=False), now_iso, normalized_id),
            )
            affected_rows = cur.rowcount
        conn.commit()
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "DB save projects(project_data merge) project_id=%s affected_rows=%s elapsed_ms=%s",
        normalized_id,
        affected_rows,
        elapsed_ms,
    )


def upsert_project(
    connection_string: str,
    *,
    project_id: str,
    created_at: str,
    updated_at: str,
    project_data: dict[str, Any],
    zep_graph_id: str | None = None,
    graph_backend: str | None = None,
    project_workspace_id: str | None = None,
    zep_graph_address: str | None = None,
    prompt_label_id: int | None = None,
    prompt_label: str | None = None,
) -> None:
    computed_has_built_graph = str(project_data.get("status") or "").strip().lower() == "graph_completed"

    started_at = time.perf_counter()
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (
                    project_id,
                    created_at,
                    updated_at,
                    project_data,
                    zep_graph_id,
                    graph_backend,
                    project_workspace_id,
                    zep_graph_address,
                    has_built_graph,
                    prompt_label_id,
                    prompt_label
                )
                VALUES (
                    %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s,
                    COALESCE(
                        %s,
                        (
                            SELECT id
                            FROM prompt_labels
                            WHERE LOWER(name) = LOWER(%s)
                            LIMIT 1
                        )
                    ),
                    %s
                )
                ON CONFLICT (project_id)
                DO UPDATE SET
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    project_data = EXCLUDED.project_data,
                    zep_graph_id = EXCLUDED.zep_graph_id,
                    graph_backend = EXCLUDED.graph_backend,
                    project_workspace_id = EXCLUDED.project_workspace_id,
                    zep_graph_address = EXCLUDED.zep_graph_address,
                    has_built_graph = EXCLUDED.has_built_graph,
                    prompt_label_id = EXCLUDED.prompt_label_id,
                    prompt_label = EXCLUDED.prompt_label
                """,
                (
                    project_id,
                    created_at,
                    updated_at,
                    json.dumps(project_data, ensure_ascii=False),
                    zep_graph_id,
                    graph_backend,
                    project_workspace_id,
                    zep_graph_address,
                    computed_has_built_graph,
                    prompt_label_id,
                    prompt_label,
                    prompt_label,
                ),
            )
        conn.commit()
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "DB save projects(upsert) project_id=%s elapsed_ms=%s",
        project_id,
        elapsed_ms,
    )


def get_project_data(connection_string: str, project_id: str) -> dict[str, Any] | None:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.project_data,
                    p.zep_graph_id,
                    p.graph_backend,
                    p.project_workspace_id,
                    p.zep_graph_address,
                    p.has_built_graph,
                    graph_build_latest.status AS latest_graph_build_status,
                    graph_build_latest.total_batches AS latest_total_batches,
                    graph_build_latest.last_completed_batch_index AS latest_last_completed_batch_index,
                    graph_build_latest.batch_size AS latest_batch_size,
                    graph_build_latest.resume_state AS latest_resume_state,
                    graph_build_latest.updated_at AS latest_graph_build_updated_at,
                    graph_build_latest.task_id AS latest_graph_build_task_id,
                    COALESCE(label_by_id.name, label_by_name.name, p.prompt_label) AS prompt_label,
                    COALESCE(p.prompt_label_id, label_by_name.id) AS prompt_label_id
                FROM projects AS p
                LEFT JOIN LATERAL (
                    SELECT
                        gb.status,
                        gb.total_batches,
                        gb.last_completed_batch_index,
                        gb.batch_size,
                        gb.resume_state,
                        gb.updated_at,
                        gb.task_id
                    FROM graph_build AS gb
                    WHERE
                        gb.project_id = p.project_id
                        AND LOWER(gb.task_type) = 'graph_build'
                    ORDER BY gb.updated_at DESC
                    LIMIT 1
                ) AS graph_build_latest ON TRUE
                LEFT JOIN prompt_labels AS label_by_id
                    ON p.prompt_label_id = label_by_id.id
                LEFT JOIN prompt_labels AS label_by_name
                    ON p.prompt_label_id IS NULL
                    AND p.prompt_label IS NOT NULL
                    AND LOWER(p.prompt_label) = LOWER(label_by_name.name)
                WHERE p.project_id = %s
                """,
                (project_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    project_data = _decode_project_data(row[0])
    zep_graph_id = row[1]
    graph_backend = row[2]
    project_workspace_id = row[3]
    zep_graph_address = row[4]
    persisted_has_built_graph = bool(row[5])
    latest_graph_build_status = row[6]
    latest_total_batches = row[7]
    latest_last_completed_batch_index = row[8]
    latest_batch_size = row[9]
    latest_resume_state = row[10]
    latest_graph_build_updated_at = row[11]
    latest_graph_build_task_id = row[12]
    prompt_label = row[13]
    prompt_label_id = row[14]
    if zep_graph_id and not project_data.get("zep_graph_id"):
        project_data["zep_graph_id"] = zep_graph_id
    if graph_backend:
        # Always prefer the normalized DB column over embedded JSON value.
        # This prevents stale `project_data.graph_backend` (e.g. "neo4j")
        # from overriding the true stored column value (e.g. "oracle").
        project_data["graph_backend"] = graph_backend
    if project_workspace_id and not project_data.get("project_workspace_id"):
        project_data["project_workspace_id"] = project_workspace_id
    if zep_graph_address and not project_data.get("zep_graph_address"):
        project_data["zep_graph_address"] = zep_graph_address
    project_data["has_built_graph"] = _derive_has_built_graph(
        latest_graph_build_status=latest_graph_build_status,
        fallback_value=persisted_has_built_graph,
        project_status=project_data.get("status"),
    )
    project_data["graph_resume_candidate"] = _build_graph_resume_candidate(
        latest_graph_build_status=latest_graph_build_status,
        total_batches=latest_total_batches,
        last_completed_batch_index=latest_last_completed_batch_index,
        batch_size=latest_batch_size,
        resume_state=latest_resume_state,
        updated_at=latest_graph_build_updated_at,
        task_id=latest_graph_build_task_id,
    )
    project_data["prompt_label"] = prompt_label
    if prompt_label_id is not None:
        project_data["prompt_label_id"] = int(prompt_label_id)
    return project_data


def list_projects_data(connection_string: str, limit: int) -> list[dict[str, Any]]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.project_data,
                    p.zep_graph_id,
                    p.graph_backend,
                    p.project_workspace_id,
                    p.zep_graph_address,
                    p.has_built_graph,
                    graph_build_latest.status AS latest_graph_build_status,
                    graph_build_latest.total_batches AS latest_total_batches,
                    graph_build_latest.last_completed_batch_index AS latest_last_completed_batch_index,
                    graph_build_latest.batch_size AS latest_batch_size,
                    graph_build_latest.resume_state AS latest_resume_state,
                    graph_build_latest.updated_at AS latest_graph_build_updated_at,
                    graph_build_latest.task_id AS latest_graph_build_task_id,
                    COALESCE(label_by_id.name, label_by_name.name, p.prompt_label) AS prompt_label,
                    COALESCE(p.prompt_label_id, label_by_name.id) AS prompt_label_id
                FROM projects AS p
                LEFT JOIN LATERAL (
                    SELECT
                        gb.status,
                        gb.total_batches,
                        gb.last_completed_batch_index,
                        gb.batch_size,
                        gb.resume_state,
                        gb.updated_at,
                        gb.task_id
                    FROM graph_build AS gb
                    WHERE
                        gb.project_id = p.project_id
                        AND LOWER(gb.task_type) = 'graph_build'
                    ORDER BY gb.updated_at DESC
                    LIMIT 1
                ) AS graph_build_latest ON TRUE
                LEFT JOIN prompt_labels AS label_by_id
                    ON p.prompt_label_id = label_by_id.id
                LEFT JOIN prompt_labels AS label_by_name
                    ON p.prompt_label_id IS NULL
                    AND p.prompt_label IS NOT NULL
                    AND LOWER(p.prompt_label) = LOWER(label_by_name.name)
                ORDER BY p.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    projects: list[dict[str, Any]] = []
    for row in rows:
        project_data = _decode_project_data(row[0])
        zep_graph_id = row[1]
        graph_backend = row[2]
        project_workspace_id = row[3]
        zep_graph_address = row[4]
        persisted_has_built_graph = bool(row[5])
        latest_graph_build_status = row[6]
        latest_total_batches = row[7]
        latest_last_completed_batch_index = row[8]
        latest_batch_size = row[9]
        latest_resume_state = row[10]
        latest_graph_build_updated_at = row[11]
        latest_graph_build_task_id = row[12]
        prompt_label = row[13]
        prompt_label_id = row[14]
        if zep_graph_id and not project_data.get("zep_graph_id"):
            project_data["zep_graph_id"] = zep_graph_id
        if graph_backend:
            # Always prefer the normalized DB column over embedded JSON value.
            project_data["graph_backend"] = graph_backend
        if project_workspace_id and not project_data.get("project_workspace_id"):
            project_data["project_workspace_id"] = project_workspace_id
        if zep_graph_address and not project_data.get("zep_graph_address"):
            project_data["zep_graph_address"] = zep_graph_address
        project_data["has_built_graph"] = _derive_has_built_graph(
            latest_graph_build_status=latest_graph_build_status,
            fallback_value=persisted_has_built_graph,
            project_status=project_data.get("status"),
        )
        project_data["graph_resume_candidate"] = _build_graph_resume_candidate(
            latest_graph_build_status=latest_graph_build_status,
            total_batches=latest_total_batches,
            last_completed_batch_index=latest_last_completed_batch_index,
            batch_size=latest_batch_size,
            resume_state=latest_resume_state,
            updated_at=latest_graph_build_updated_at,
            task_id=latest_graph_build_task_id,
        )
        project_data["prompt_label"] = prompt_label
        if prompt_label_id is not None:
            project_data["prompt_label_id"] = int(prompt_label_id)
        projects.append(project_data)
    return projects


def delete_project_data(connection_string: str, project_id: str) -> bool:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE project_id = %s", (project_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def update_project_extracted_text(
    connection_string: str, project_id: str, text: str, updated_at: str
) -> None:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE projects
                SET
                    extracted_text = %s,
                    updated_at = %s,
                    project_data = jsonb_set(
                        project_data,
                        '{updated_at}',
                        to_jsonb(%s::text),
                        true
                    )
                WHERE project_id = %s
                """,
                (text, updated_at, updated_at, project_id),
            )
        conn.commit()


def get_project_extracted_text(connection_string: str, project_id: str) -> str | None:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extracted_text FROM projects WHERE project_id = %s",
                (project_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    return row[0]


def ensure_prompt_label_data(
    connection_string: str,
    *,
    name: str,
    now_iso: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            # Enforce case-insensitive uniqueness for label names at write time.
            # If a label already exists with different casing, preserve existing casing.
            cur.execute(
                """
                SELECT name
                FROM prompt_labels
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,),
            )
            existing_row = cur.fetchone()
            effective_name = str((existing_row or [name])[0] or name)
            cur.execute(
                """
                INSERT INTO prompt_labels (name, project_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name)
                DO UPDATE SET
                    project_id = COALESCE(prompt_labels.project_id, EXCLUDED.project_id),
                    updated_at = EXCLUDED.updated_at
                RETURNING id, name
                """,
                (effective_name, project_id, now_iso, now_iso),
            )
            label_row = cur.fetchone()
            _refresh_prompt_label_stats(cur, now_iso)
        conn.commit()
    return {
        "id": int((label_row or [0])[0] or 0) or None,
        "name": str((label_row or ["", effective_name])[1] or effective_name),
    }


def _refresh_prompt_label_stats(cur: Any, now_iso: str) -> int:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_label_stats (
            stats_key TEXT PRIMARY KEY,
            total_labels INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("SELECT COUNT(*)::INT FROM prompt_labels")
    total_labels = int((cur.fetchone() or [0])[0] or 0)
    cur.execute(
        """
        INSERT INTO prompt_label_stats (stats_key, total_labels, updated_at)
        VALUES ('global', %s, %s)
        ON CONFLICT (stats_key)
        DO UPDATE SET
            total_labels = EXCLUDED.total_labels,
            updated_at = EXCLUDED.updated_at
        """,
        (total_labels, now_iso),
    )
    return total_labels


def get_prompt_label_stats_data(connection_string: str) -> dict[str, Any]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT total_labels, updated_at
                FROM prompt_label_stats
                WHERE stats_key = 'global'
                """
            )
            row = cur.fetchone()
            if row is None:
                now_iso = datetime.now().isoformat()
                total_labels = _refresh_prompt_label_stats(cur, now_iso)
                conn.commit()
                return {
                    "total_labels": total_labels,
                    "updated_at": now_iso,
                }

    return {
        "total_labels": int(row[0] or 0),
        "updated_at": str(row[1] or ""),
    }


def list_prompt_labels_data(connection_string: str) -> list[dict[str, Any]]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    labels.id,
                    labels.name,
                    labels.project_id,
                    labels.created_at,
                    labels.updated_at,
                    COUNT(projects.project_id)::INT AS project_count
                FROM prompt_labels AS labels
                LEFT JOIN projects
                    ON projects.prompt_label_id = labels.id
                    OR (
                        projects.prompt_label_id IS NULL
                        AND projects.prompt_label IS NOT NULL
                        AND LOWER(projects.prompt_label) = LOWER(labels.name)
                    )
                GROUP BY labels.id, labels.name, labels.project_id, labels.created_at, labels.updated_at
                ORDER BY labels.name ASC
                """
            )
            rows = cur.fetchall()

    return [
        {
            "id": int(row[0]) if row[0] is not None else None,
            "name": row[1],
            "project_id": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "project_count": row[5],
        }
        for row in rows
    ]


def delete_prompt_label_data(connection_string: str, name: str) -> tuple[bool, str]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name
                FROM prompt_labels
                WHERE LOWER(name) = LOWER(%s)
                LIMIT 1
                """,
                (name,),
            )
            label_row = cur.fetchone()
            if not label_row:
                return False, f"Category label not found: {name}"
            label_id = label_row[0]
            resolved_name = str(label_row[1] or name)

            cur.execute(
                """
                SELECT COUNT(*)::INT
                FROM projects
                WHERE prompt_label_id = %s
                    OR (
                        prompt_label_id IS NULL
                        AND prompt_label IS NOT NULL
                        AND LOWER(prompt_label) = LOWER(%s)
                    )
                """,
                (label_id, resolved_name),
            )
            projects_using_label = (cur.fetchone() or [0])[0]
            if projects_using_label > 0:
                return (
                    False,
                    f"Label '{resolved_name}' is used by {projects_using_label} project(s) and cannot be deleted.",
                )

            cur.execute(
                "DELETE FROM prompt_labels WHERE id = %s",
                (label_id,),
            )
            deleted = cur.rowcount > 0
            if deleted:
                _refresh_prompt_label_stats(cur, now_iso=datetime.now().isoformat())
        conn.commit()

    if deleted:
        return True, f"Category label deleted: {resolved_name}"
    return False, f"Category label not found: {name}"


def insert_ontology_version_data(
    connection_string: str,
    *,
    project_id: str,
    source: str,
    ontology_json: dict[str, Any],
    ontology_hash: str,
    parent_version_ids: list[int] | None = None,
    created_by_task_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id is required")
    normalized_source = str(source or "").strip() or "manual"
    normalized_hash = str(ontology_hash or "").strip()
    if not normalized_hash:
        raise ValueError("ontology_hash is required")
    normalized_parent_ids = [
        int(value)
        for value in (parent_version_ids or [])
        if str(value).strip()
    ]
    now_iso = str(created_at or datetime.now().isoformat())
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ontology_versions (
                    project_id,
                    source,
                    ontology_json,
                    ontology_hash,
                    parent_version_ids,
                    created_by_task_id,
                    created_at
                )
                VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, %s, %s)
                RETURNING id, project_id, source, ontology_hash, parent_version_ids, created_by_task_id, created_at
                """,
                (
                    normalized_project_id,
                    normalized_source,
                    json.dumps(ontology_json or {}, ensure_ascii=False),
                    normalized_hash,
                    json.dumps(normalized_parent_ids, ensure_ascii=False),
                    str(created_by_task_id or "").strip() or None,
                    now_iso,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "id": int((row or [0])[0] or 0),
        "project_id": str((row or ["", "", "", "", "", "", ""])[1] or ""),
        "source": str((row or ["", "", "", "", "", "", ""])[2] or ""),
        "ontology_hash": str((row or ["", "", "", "", "", "", ""])[3] or ""),
        "parent_version_ids": list((row or ["", "", "", "", [], "", ""])[4] or []),
        "created_by_task_id": str((row or ["", "", "", "", "", "", ""])[5] or "") or None,
        "created_at": str((row or ["", "", "", "", "", "", ""])[6] or ""),
    }


def get_latest_ontology_version_data(
    connection_string: str,
    *,
    project_id: str,
) -> dict[str, Any] | None:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return None
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    project_id,
                    source,
                    ontology_json,
                    ontology_hash,
                    parent_version_ids,
                    created_by_task_id,
                    created_at
                FROM ontology_versions
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_project_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": int(row[0]),
        "project_id": str(row[1] or ""),
        "source": str(row[2] or ""),
        "ontology_json": _decode_project_data(row[3]) if row[3] is not None else {},
        "ontology_hash": str(row[4] or ""),
        "parent_version_ids": list(row[5] or []),
        "created_by_task_id": str(row[6] or "") or None,
        "created_at": str(row[7] or ""),
    }


def list_ontology_versions_data(
    connection_string: str,
    *,
    project_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return []
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    project_id,
                    source,
                    ontology_json,
                    ontology_hash,
                    parent_version_ids,
                    created_by_task_id,
                    created_at
                FROM ontology_versions
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (normalized_project_id, int(limit)),
            )
            rows = cur.fetchall()
    return [
        {
            "id": int(row[0]),
            "project_id": str(row[1] or ""),
            "source": str(row[2] or ""),
            "ontology_json": _decode_project_data(row[3]) if row[3] is not None else {},
            "ontology_hash": str(row[4] or ""),
            "parent_version_ids": list(row[5] or []),
            "created_by_task_id": str(row[6] or "") or None,
            "created_at": str(row[7] or ""),
        }
        for row in rows
    ]


def insert_graph_build_data(
    connection_string: str,
    *,
    task_id: str,
    task_type: str,
    status: str,
    progress: int = 0,
    message: str = "",
    project_id: str | None = None,
    graph_id: str | None = None,
    graph_name: str | None = None,
    graph_backend: str | None = None,
    chunk_mode: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
    progress_detail: dict[str, Any] | None = None,
    source_text_hash: str | None = None,
    ontology_hash: str | None = None,
    ontology_version_id: int | None = None,
    build_identity_key: str | None = None,
    batch_size: int | None = None,
    total_chunks: int | None = None,
    total_batches: int | None = None,
    last_completed_batch_index: int | None = None,
    resume_state: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> None:
    now_iso = datetime.now().isoformat()
    resolved_created_at = str(created_at or now_iso)
    resolved_updated_at = str(updated_at or now_iso)
    resolved_progress = int(progress if progress is not None else 0)
    resolved_message = str(message or "")
    # NOT NULL columns: explicit NULL in INSERT bypasses DB DEFAULT — use safe fallbacks.
    resolved_last_batch = (
        int(last_completed_batch_index)
        if last_completed_batch_index is not None
        else -1
    )
    resolved_resume_state = str(resume_state or "").strip() or "new"

    started_at = time.perf_counter()
    affected_rows = 0
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO graph_build (
                    task_id,
                    task_type,
                    project_id,
                    graph_id,
                    graph_name,
                    graph_backend,
                    chunk_mode,
                    chunk_size,
                    chunk_overlap,
                    status,
                    progress,
                    message,
                    error,
                    result,
                    progress_detail,
                    source_text_hash,
                    ontology_hash,
                    ontology_version_id,
                    build_identity_key,
                    batch_size,
                    total_chunks,
                    total_batches,
                    last_completed_batch_index,
                    resume_state,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (task_id)
                DO NOTHING
                """,
                (
                    task_id,
                    task_type,
                    project_id,
                    graph_id,
                    graph_name,
                    graph_backend,
                    chunk_mode,
                    chunk_size,
                    chunk_overlap,
                    status,
                    resolved_progress,
                    resolved_message,
                    error,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    json.dumps(progress_detail or {}, ensure_ascii=False),
                    source_text_hash,
                    ontology_hash,
                    ontology_version_id,
                    build_identity_key,
                    batch_size,
                    total_chunks,
                    total_batches,
                    resolved_last_batch,
                    resolved_resume_state,
                    resolved_created_at,
                    resolved_updated_at,
                ),
            )
            affected_rows = cur.rowcount
        conn.commit()
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "DB save graph_build(insert) task_id=%s status=%s affected_rows=%s elapsed_ms=%s",
        task_id,
        status,
        affected_rows,
        elapsed_ms,
    )


def update_graph_build_status(
    connection_string: str,
    *,
    task_id: str,
    status: str,
    progress: int,
    message: str,
    error: str | None = None,
    result: dict[str, Any] | None = None,
    progress_detail: dict[str, Any] | None = None,
    source_text_hash: str | None = None,
    ontology_hash: str | None = None,
    ontology_version_id: int | None = None,
    build_identity_key: str | None = None,
    chunk_mode: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    updated_at: str | None = None,
) -> bool:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return False

    started_at = time.perf_counter()
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE graph_build
                SET
                    status = %s,
                    progress = %s,
                    message = %s,
                    error = %s,
                    result = %s::jsonb,
                    progress_detail = %s::jsonb,
                    source_text_hash = COALESCE(graph_build.source_text_hash, %s),
                    ontology_hash = COALESCE(graph_build.ontology_hash, %s),
                    ontology_version_id = COALESCE(graph_build.ontology_version_id, %s),
                    build_identity_key = COALESCE(graph_build.build_identity_key, %s),
                    chunk_mode = COALESCE(graph_build.chunk_mode, %s),
                    chunk_size = COALESCE(graph_build.chunk_size, %s),
                    chunk_overlap = COALESCE(graph_build.chunk_overlap, %s),
                    updated_at = %s
                WHERE task_id = %s
                """,
                (
                    status,
                    int(progress),
                    str(message or ""),
                    error,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    json.dumps(progress_detail or {}, ensure_ascii=False),
                    source_text_hash,
                    ontology_hash,
                    ontology_version_id,
                    build_identity_key,
                    chunk_mode,
                    chunk_size,
                    chunk_overlap,
                    str(updated_at or datetime.now().isoformat()),
                    normalized_task_id,
                ),
            )
            updated = cur.rowcount > 0
        conn.commit()
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "DB save graph_build(update_status) task_id=%s status=%s updated=%s elapsed_ms=%s",
        normalized_task_id,
        status,
        updated,
        elapsed_ms,
    )
    return updated


def get_graph_build_task_data(connection_string: str, task_id: str) -> dict[str, Any] | None:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    task_id,
                    task_type,
                    project_id,
                    status,
                    updated_at
                FROM graph_build
                WHERE task_id = %s
                LIMIT 1
                """,
                (task_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    return {
        "task_id": str(row[0] or ""),
        "task_type": str(row[1] or ""),
        "project_id": str(row[2] or "") or None,
        "status": str(row[3] or ""),
        "updated_at": str(row[4] or ""),
    }


def get_latest_resumable_graph_build_data(
    connection_string: str,
    *,
    project_id: str,
    build_identity_key: str,
    exclude_task_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Latest resumable graph_build row for an identity.

    exclude_task_id: omit this task_id so a brand-new build row (just upserted for the
    current run) does not win ORDER BY updated_at DESC over an older interrupted run
    with checkpoint data — that mismatch prevented post-restart resume.
    """
    normalized_project_id = str(project_id or "").strip()
    normalized_identity_key = str(build_identity_key or "").strip()
    normalized_exclude = str(exclude_task_id or "").strip()
    if not normalized_project_id or not normalized_identity_key:
        return None

    params: list[Any] = [normalized_project_id, normalized_identity_key]
    exclude_clause = ""
    if normalized_exclude:
        exclude_clause = " AND task_id <> %s "
        params.append(normalized_exclude)

    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    task_id,
                    project_id,
                    graph_id,
                    status,
                    chunk_mode,
                    chunk_size,
                    chunk_overlap,
                    source_text_hash,
                    ontology_hash,
                    build_identity_key,
                    batch_size,
                    total_chunks,
                    total_batches,
                    last_completed_batch_index,
                    resume_state,
                    updated_at
                FROM graph_build
                WHERE
                    project_id = %s
                    AND build_identity_key = %s
                    AND LOWER(COALESCE(task_type, '')) = 'graph_build'
                    AND LOWER(COALESCE(status, '')) IN ('pending', 'processing', 'failed', 'cancelled')
                    {exclude_clause}
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                params,
            )
            row = cur.fetchone()

    if not row:
        return None

    return {
        "task_id": str(row[0] or ""),
        "project_id": str(row[1] or ""),
        "graph_id": str(row[2] or "") or None,
        "status": str(row[3] or ""),
        "chunk_mode": str(row[4] or ""),
        "chunk_size": int(row[5]) if row[5] is not None else None,
        "chunk_overlap": int(row[6]) if row[6] is not None else None,
        "source_text_hash": str(row[7] or "") or None,
        "ontology_hash": str(row[8] or "") or None,
        "build_identity_key": str(row[9] or "") or None,
        "batch_size": int(row[10]) if row[10] is not None else None,
        "total_chunks": int(row[11]) if row[11] is not None else None,
        "total_batches": int(row[12]) if row[12] is not None else None,
        "last_completed_batch_index": int(row[13]) if row[13] is not None else -1,
        "resume_state": str(row[14] or "") or None,
        "updated_at": str(row[15] or ""),
    }


def get_latest_graph_build_resume_candidate(
    connection_string: str,
    *,
    project_id: str,
) -> dict[str, Any] | None:
    """Latest graph_build row only when latest status is unsuccessful."""
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return None

    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    task_id,
                    status,
                    total_batches,
                    last_completed_batch_index,
                    batch_size,
                    resume_state,
                    updated_at
                FROM graph_build
                WHERE
                    project_id = %s
                    AND LOWER(COALESCE(task_type, '')) = 'graph_build'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (normalized_project_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    status = str(row[1] or "").strip().lower()
    if status == "completed":
        return None

    return {
        "task_id": str(row[0] or ""),
        "status": status,
        "total_batches": int(row[2]) if row[2] is not None else None,
        "last_completed_batch_index": int(row[3]) if row[3] is not None else -1,
        "batch_size": int(row[4]) if row[4] is not None else None,
        "resume_state": str(row[5] or "") or None,
        "updated_at": str(row[6] or ""),
    }


def update_graph_build_checkpoint(
    connection_string: str,
    *,
    task_id: str,
    last_completed_batch_index: int,
    total_batches: int | None = None,
    total_chunks: int | None = None,
    batch_size: int | None = None,
    resume_state: str | None = None,
    updated_at: str | None = None,
) -> bool:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return False

    now_iso = str(updated_at or datetime.now().isoformat())
    resolved_last_idx = int(last_completed_batch_index)

    started_at = time.perf_counter()
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE graph_build
                SET
                    last_completed_batch_index = GREATEST(
                        COALESCE(last_completed_batch_index, -1),
                        %s
                    ),
                    total_batches = COALESCE(%s, total_batches),
                    total_chunks = COALESCE(%s, total_chunks),
                    batch_size = COALESCE(%s, batch_size),
                    resume_state = COALESCE(%s, resume_state),
                    updated_at = %s
                WHERE task_id = %s
                """,
                (
                    resolved_last_idx,
                    total_batches,
                    total_chunks,
                    batch_size,
                    resume_state,
                    now_iso,
                    normalized_task_id,
                ),
            )
            updated = cur.rowcount > 0
        conn.commit()
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "DB save graph_build(update_checkpoint) task_id=%s last_completed_batch_index=%s updated=%s elapsed_ms=%s",
        normalized_task_id,
        resolved_last_idx,
        updated,
        elapsed_ms,
    )
    return updated
