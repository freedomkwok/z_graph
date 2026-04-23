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

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = APP_DIR.parent
ENV_FILE = BACKEND_DIR / ".env"
FALLBACK_ENV_FILE = BACKEND_DIR / ".env.example"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv(FALLBACK_ENV_FILE)


class Settings(BaseSettings):
    app_name: str = "zep_graph_backend"
    app_env: str = "development"
    api_prefix: str = "/api"
    host: str = "0.0.0.0"
    port: int = 8000
    upload_folder: str = str(BACKEND_DIR / "uploads")
    storage: str = "file"
    project_storage_connection_string: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "z_graph"
    postgres_user: str = "z_graph"
    postgres_password: str = "zep_graph_password"
    llm_provider: str = "openai"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model_name: str = "gpt-4o-mini"
    max_text_length_for_llm: int = 128000
    llm_max_retries: int = 3
    llm_initial_delay_seconds: float = 1.0
    llm_max_delay_seconds: float = 30.0
    llm_backoff_factor: float = 2.0
    task_poll_interval_ms: int = 2000
    # Slower interval for full graph payload polling while a graph build is in progress (frontend).
    graph_data_poll_interval_ms: int = 10000
    # Episodes per batch when pushing chunks to the graph backend (overridable per /api/build request).
    graph_build_batch_size: int = 5
    # Timeout budget per graph for warm-up calls triggered by GET /api/project/{project_id}.
    project_get_warmup_timeout_seconds: float = 3.0
    # Skip repeated GET warm-up for same project/ontology/graph key within this window.
    project_get_warmup_dedupe_ttl_seconds: int = 30
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_base_url: str | None = None
    apply_langfuse_to_graphiti_trace: bool = True
    langfuse_otel_endpoint: str | None = None
    langfuse_otel_auth: str | None = None
    zep_api_key: str | None = None
    zep_api_url: str | None = None
    zep_graph_url_template: str | None = None
    zep_backend: str | None = None
    graphiti_db: str = "neo4j"
    # Comma-separated candidate embedding models for Graphiti UI/selection.
    # Example: "text-embedding-3-large,text-embedding-3-small"
    graphiti_embedding_model: str = "text-embedding-3-large"
    graphdb_uri: str | None = None
    graphdb_user: str | None = None
    graphdb_password: str | None = None
    graphdb_dsn: str | None = None
    oracle_use_rdf: bool = False
    oracle_log_queries: bool = False
    oracle_rdf_network_owner: str | None = None
    oracle_rdf_network_name: str | None = None
    oracle_rdf_graph_name: str | None = None
    oracle_rdf_tablespace: str | None = None
    oracle_pg_graph_id: str | None = None
    oracle_pool_min: int | None = None
    oracle_pool_max: int | None = None
    oracle_pool_increment: int | None = None
    oracle_max_coroutines: int | None = 20
    openai_api_key: str | None = None
    openai_base_url: str | None = None

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def storage_connection_string(self) -> str:
        if self.project_storage_connection_string:
            return self.project_storage_connection_string
        return self.database_url

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE if ENV_FILE.exists() else FALLBACK_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


class Config:
    # Backward-compatible static access for older modules.
    APP_NAME = settings.app_name
    APP_ENV = settings.app_env
    API_PREFIX = settings.api_prefix
    HOST = settings.host
    PORT = settings.port

    UPLOAD_FOLDER = settings.upload_folder
    STORAGE = settings.storage
    PROJECT_STORAGE_CONNECTION_STRING = settings.storage_connection_string

    POSTGRES_HOST = settings.postgres_host
    POSTGRES_PORT = settings.postgres_port
    POSTGRES_DB = settings.postgres_db
    POSTGRES_USER = settings.postgres_user
    POSTGRES_PASSWORD = settings.postgres_password
    DATABASE_URL = settings.database_url

    LLM_PROVIDER = settings.llm_provider
    LLM_API_KEY = settings.llm_api_key
    LLM_BASE_URL = settings.llm_base_url
    LLM_MODEL_NAME = settings.llm_model_name
    MAX_TEXT_LENGTH_FOR_LLM = settings.max_text_length_for_llm
    LLM_MAX_RETRIES = settings.llm_max_retries
    LLM_INITIAL_DELAY_SECONDS = settings.llm_initial_delay_seconds
    LLM_MAX_DELAY_SECONDS = settings.llm_max_delay_seconds
    LLM_BACKOFF_FACTOR = settings.llm_backoff_factor
    TASK_POLL_INTERVAL_MS = settings.task_poll_interval_ms
    GRAPH_DATA_POLL_INTERVAL_MS = settings.graph_data_poll_interval_ms
    GRAPH_BUILD_BATCH_SIZE = settings.graph_build_batch_size
    PROJECT_GET_WARMUP_TIMEOUT_SECONDS = settings.project_get_warmup_timeout_seconds
    PROJECT_GET_WARMUP_DEDUPE_TTL_SECONDS = settings.project_get_warmup_dedupe_ttl_seconds

    LANGFUSE_PUBLIC_KEY = settings.langfuse_public_key
    LANGFUSE_SECRET_KEY = settings.langfuse_secret_key
    LANGFUSE_HOST = settings.langfuse_host
    LANGFUSE_BASE_URL = settings.langfuse_base_url
    APPLY_LANGFUSE_TO_GRAPHITI_TRACE = settings.apply_langfuse_to_graphiti_trace
    LANGFUSE_OTEL_ENDPOINT = settings.langfuse_otel_endpoint
    LANGFUSE_OTEL_AUTH = settings.langfuse_otel_auth

    ZEP_API_KEY = settings.zep_api_key
    ZEP_API_URL = settings.zep_api_url
    ZEP_GRAPH_URL_TEMPLATE = settings.zep_graph_url_template
    # Prefer ZEP_BACKEND; keep ZEP_CORE for backward compatibility.
    ZEP_BACKEND = settings.zep_backend
    GRAPHITI_DB = settings.graphiti_db
    GRAPHITI_EMBEDDING_MODEL = str(settings.graphiti_embedding_model or "").strip()
    GRAPHITI_EMBEDDING_MODELS = [
        model.strip()
        for model in str(settings.graphiti_embedding_model or "").split(",")
        if model.strip()
    ] or ["text-embedding-3-large"]
    GRAPHITI_DEFAULT_EMBEDDING_MODEL = GRAPHITI_EMBEDDING_MODELS[0]

    GRAPHDB_URI = settings.graphdb_uri
    GRAPHDB_USER = settings.graphdb_user
    GRAPHDB_PASSWORD = settings.graphdb_password
    GRAPHDB_DSN = settings.graphdb_dsn
    ORACLE_USE_RDF = settings.oracle_use_rdf
    ORACLE_LOG_QUERIES = settings.oracle_log_queries
    ORACLE_RDF_NETWORK_OWNER = settings.oracle_rdf_network_owner
    ORACLE_RDF_NETWORK_NAME = settings.oracle_rdf_network_name
    ORACLE_RDF_GRAPH_NAME = settings.oracle_rdf_graph_name
    ORACLE_RDF_TABLESPACE = settings.oracle_rdf_tablespace
    ORACLE_PG_GRAPH_ID = settings.oracle_pg_graph_id
    ORACLE_POOL_MIN = settings.oracle_pool_min
    ORACLE_POOL_MAX = settings.oracle_pool_max
    ORACLE_POOL_INCREMENT = settings.oracle_pool_increment
    ORACLE_MAX_COROUTINES = settings.oracle_max_coroutines

    OPENAI_API_KEY = settings.openai_api_key
    OPENAI_BASE_URL = settings.openai_base_url
