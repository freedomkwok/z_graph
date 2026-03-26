from __future__ import annotations

import os
import time
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = REPO_ROOT / "database"
BACKEND_DIR = REPO_ROOT / "backend"
ENV_FILE = DATABASE_DIR / ".env"
FALLBACK_ENV_FILE = DATABASE_DIR / ".env.example"
LEGACY_ENV_FILE = BACKEND_DIR / ".env"
LEGACY_FALLBACK_ENV_FILE = BACKEND_DIR / ".env.example"
SCHEMA_SQL_PATH = REPO_ROOT / "database" / "init_tables.sql"
SEED_SQL_PATH = REPO_ROOT / "database" / "init_seed_data.sql"


def _load_env() -> None:
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    elif FALLBACK_ENV_FILE.exists():
        load_dotenv(FALLBACK_ENV_FILE)
    elif LEGACY_ENV_FILE.exists():
        # Backward compatibility for older setup that kept DB init vars in backend/.env
        load_dotenv(LEGACY_ENV_FILE)
    else:
        load_dotenv(LEGACY_FALLBACK_ENV_FILE)


def _default_postgres_port() -> str:
    host_port = (os.getenv("POSTGRES_HOST_PORT") or "").strip()
    if host_port:
        return host_port
    return os.getenv("POSTGRES_PORT") or "5432"


def _get_connection_string() -> str:
    project_storage_connection_string = os.getenv("PROJECT_STORAGE_CONNECTION_STRING", "").strip()
    if project_storage_connection_string:
        return project_storage_connection_string

    postgres_user = os.getenv("POSTGRES_USER", "z_graph")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "zep_graph_password")
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port = _default_postgres_port()
    postgres_db = os.getenv("POSTGRES_DB", "z_graph")
    return (
        f"postgresql://{postgres_user}:{postgres_password}"
        f"@{postgres_host}:{postgres_port}/{postgres_db}"
    )


def _get_target_postgres_settings() -> dict[str, str]:
    return {
        "user": os.getenv("POSTGRES_USER", "z_graph"),
        "password": os.getenv("POSTGRES_PASSWORD", "zep_graph_password"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": _default_postgres_port(),
        "database": os.getenv("POSTGRES_DB", "z_graph"),
    }


def _get_bootstrap_connection_string(target_settings: dict[str, str]) -> str:
    bootstrap_url = os.getenv("POSTGRES_BOOTSTRAP_URL", "").strip()
    if bootstrap_url:
        return bootstrap_url

    bootstrap_user = os.getenv("POSTGRES_BOOTSTRAP_USER", "postgres")
    bootstrap_password = os.getenv("POSTGRES_BOOTSTRAP_PASSWORD", "postgres")
    bootstrap_host = os.getenv("POSTGRES_BOOTSTRAP_HOST", target_settings["host"])
    bootstrap_port = os.getenv("POSTGRES_BOOTSTRAP_PORT", target_settings["port"])
    bootstrap_db = os.getenv("POSTGRES_BOOTSTRAP_DB", "postgres")
    return (
        f"postgresql://{bootstrap_user}:{bootstrap_password}"
        f"@{bootstrap_host}:{bootstrap_port}/{bootstrap_db}"
    )


def _load_sql_statements(path: Path, *, required: bool, split_statements: bool = True) -> list[str]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"SQL file not found: {path}")
        return []

    sql_text = path.read_text(encoding="utf-8")
    if split_statements:
        statements = [stmt.strip() for stmt in sql_text.split(";") if stmt.strip()]
    else:
        statement = sql_text.strip()
        statements = [statement] if statement else []
    if required and not statements:
        raise ValueError(f"No SQL statements found in required file: {path}")
    return statements


def _connect_with_retry(connection_string: str) -> psycopg.Connection:
    max_attempts = int(os.getenv("DB_INIT_MAX_ATTEMPTS", "20"))
    retry_delay_seconds = float(os.getenv("DB_INIT_RETRY_DELAY_SECONDS", "1.5"))
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return psycopg.connect(connection_string)
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            print(
                f"Database not ready (attempt {attempt}/{max_attempts}). "
                f"Retrying in {retry_delay_seconds:.1f}s..."
            )
            time.sleep(retry_delay_seconds)

    raise RuntimeError(
        f"Failed to connect to database after {max_attempts} attempts."
    ) from last_error


def _can_connect(connection_string: str) -> bool:
    try:
        with psycopg.connect(connection_string):
            return True
    except Exception:
        return False


def _is_truthy(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_user_and_database_exists(target_settings: dict[str, str]) -> None:
    bootstrap_connection_string = _get_bootstrap_connection_string(target_settings)
    target_user = target_settings["user"]
    target_password = target_settings["password"]
    target_database = target_settings["database"]

    print(
        "Attempting DB bootstrap via admin connection "
        f"for user='{target_user}' database='{target_database}'..."
    )

    with _connect_with_retry(bootstrap_connection_string) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (target_user,))
            role_exists = cur.fetchone() is not None
            if not role_exists:
                cur.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(target_user),
                        sql.Literal(target_password),
                    )
                )
            else:
                cur.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                        sql.Identifier(target_user),
                        sql.Literal(target_password),
                    ),
                )

            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_database,))
            db_exists = cur.fetchone() is not None
            if not db_exists:
                cur.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(target_database),
                        sql.Identifier(target_user),
                    )
                )

            cur.execute(
                sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                    sql.Identifier(target_database),
                    sql.Identifier(target_user),
                )
            )


def init_tables() -> None:
    _load_env()
    target_settings = _get_target_postgres_settings()
    connection_string = _get_connection_string()
    schema_statements = _load_sql_statements(SCHEMA_SQL_PATH, required=True, split_statements=True)
    apply_seed = _is_truthy(os.getenv("DB_INIT_APPLY_SEED"), default=True)
    seed_statements = (
        _load_sql_statements(SEED_SQL_PATH, required=False, split_statements=False)
        if apply_seed
        else []
    )
    statements = [*schema_statements, *seed_statements]

    auto_provision = _is_truthy(os.getenv("DB_INIT_AUTO_PROVISION"), default=True)
    if not _can_connect(connection_string):
        if auto_provision:
            _ensure_user_and_database_exists(target_settings)
        else:
            print("Target database not reachable and DB_INIT_AUTO_PROVISION is disabled.")

    with _connect_with_retry(connection_string) as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()

    if seed_statements:
        print("Database schema initialized successfully (seed data applied).")
    else:
        print("Database schema initialized successfully.")


if __name__ == "__main__":
    init_tables()
