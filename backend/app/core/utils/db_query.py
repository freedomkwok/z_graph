from __future__ import annotations

import json
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
) -> None:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projects (project_id, created_at, updated_at, project_data)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (project_id)
                DO UPDATE SET
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at,
                    project_data = EXCLUDED.project_data
                """,
                (
                    project_id,
                    created_at,
                    updated_at,
                    json.dumps(project_data, ensure_ascii=False),
                ),
            )
        conn.commit()


def get_project_data(connection_string: str, project_id: str) -> dict[str, Any] | None:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT project_data FROM projects WHERE project_id = %s",
                (project_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    return _decode_project_data(row[0])


def list_projects_data(connection_string: str, limit: int) -> list[dict[str, Any]]:
    with _connect_postgres(connection_string) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT project_data
                FROM projects
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    return [_decode_project_data(row[0]) for row in rows]


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
