from __future__ import annotations

import json
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

_POSTGRES_SCHEMA_INITIALIZED = False


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
    prompt_label: str | None = None,
) -> None:
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
                    prompt_label
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id)
                DO UPDATE SET
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    project_data = EXCLUDED.project_data,
                    zep_graph_id = EXCLUDED.zep_graph_id,
                    graph_backend = EXCLUDED.graph_backend,
                    project_workspace_id = EXCLUDED.project_workspace_id,
                    zep_graph_address = EXCLUDED.zep_graph_address,
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
                    prompt_label,
                ),
            )
        conn.commit()


def get_project_data(connection_string: str, project_id: str) -> dict[str, Any] | None:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT project_data, zep_graph_id, graph_backend, project_workspace_id, zep_graph_address, prompt_label
                FROM projects
                WHERE project_id = %s
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
    prompt_label = row[5]
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
    if prompt_label and not project_data.get("prompt_label"):
        project_data["prompt_label"] = prompt_label
    return project_data


def list_projects_data(connection_string: str, limit: int) -> list[dict[str, Any]]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT project_data, zep_graph_id, graph_backend, project_workspace_id, zep_graph_address, prompt_label
                FROM projects
                ORDER BY created_at DESC
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
        prompt_label = row[5]
        if zep_graph_id and not project_data.get("zep_graph_id"):
            project_data["zep_graph_id"] = zep_graph_id
        if graph_backend:
            # Always prefer the normalized DB column over embedded JSON value.
            project_data["graph_backend"] = graph_backend
        if project_workspace_id and not project_data.get("project_workspace_id"):
            project_data["project_workspace_id"] = project_workspace_id
        if zep_graph_address and not project_data.get("zep_graph_address"):
            project_data["zep_graph_address"] = zep_graph_address
        if prompt_label and not project_data.get("prompt_label"):
            project_data["prompt_label"] = prompt_label
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
) -> None:
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
                """,
                (effective_name, project_id, now_iso, now_iso),
            )
            _refresh_prompt_label_stats(cur, now_iso)
        conn.commit()


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
                    labels.name,
                    labels.project_id,
                    labels.created_at,
                    labels.updated_at,
                    COUNT(projects.project_id)::INT AS project_count
                FROM prompt_labels AS labels
                LEFT JOIN projects
                    ON projects.prompt_label = labels.name
                GROUP BY labels.name, labels.created_at, labels.updated_at
                ORDER BY labels.name ASC
                """
            )
            rows = cur.fetchall()

    return [
        {
            "name": row[0],
            "project_id": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "project_count": row[4],
        }
        for row in rows
    ]


def delete_prompt_label_data(connection_string: str, name: str) -> tuple[bool, str]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::INT FROM projects WHERE prompt_label = %s",
                (name,),
            )
            projects_using_label = (cur.fetchone() or [0])[0]
            if projects_using_label > 0:
                return (
                    False,
                    f"Label '{name}' is used by {projects_using_label} project(s) and cannot be deleted.",
                )

            cur.execute(
                "DELETE FROM prompt_labels WHERE name = %s",
                (name,),
            )
            deleted = cur.rowcount > 0
            if deleted:
                _refresh_prompt_label_stats(cur, now_iso=datetime.now().isoformat())
        conn.commit()

    if deleted:
        return True, f"Category label deleted: {name}"
    return False, f"Category label not found: {name}"
