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
    postgres_db: str = "zep_graph"
    postgres_user: str = "zep_graph"
    postgres_password: str = "zep_graph_password"
    postgres_url: str | None = None
    llm_provider: str = "openai"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model_name: str = "gpt-4o-mini"
    llm_max_retries: int = 3
    llm_initial_delay_seconds: float = 1.0
    llm_max_delay_seconds: float = 30.0
    llm_backoff_factor: float = 2.0
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_base_url: str | None = None
    zep_api_key: str | None = None
    zep_api_url: str | None = None
    zep_graph_url_template: str | None = None
    zep_backend: str | None = None
    graphdb_uri: str | None = None
    graphdb_user: str | None = None
    graphdb_password: str | None = None
    graphdb_dsn: str | None = None

    @property
    def database_url(self) -> str:
        if self.postgres_url:
            return self.postgres_url
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
    POSTGRES_URL = settings.postgres_url
    DATABASE_URL = settings.database_url

    LLM_PROVIDER = settings.llm_provider
    LLM_API_KEY = settings.llm_api_key
    LLM_BASE_URL = settings.llm_base_url
    LLM_MODEL_NAME = settings.llm_model_name
    LLM_MAX_RETRIES = settings.llm_max_retries
    LLM_INITIAL_DELAY_SECONDS = settings.llm_initial_delay_seconds
    LLM_MAX_DELAY_SECONDS = settings.llm_max_delay_seconds
    LLM_BACKOFF_FACTOR = settings.llm_backoff_factor

    LANGFUSE_PUBLIC_KEY = settings.langfuse_public_key
    LANGFUSE_SECRET_KEY = settings.langfuse_secret_key
    LANGFUSE_HOST = settings.langfuse_host
    LANGFUSE_BASE_URL = settings.langfuse_base_url

    ZEP_API_KEY = settings.zep_api_key
    ZEP_API_URL = settings.zep_api_url
    ZEP_GRAPH_URL_TEMPLATE = settings.zep_graph_url_template
    # Prefer ZEP_BACKEND; keep ZEP_CORE for backward compatibility.
    ZEP_BACKEND = settings.zep_backend

    GRAPHDB_URI = settings.graphdb_uri
    GRAPHDB_USER = settings.graphdb_user
    GRAPHDB_PASSWORD = settings.graphdb_password
    GRAPHDB_DSN = settings.graphdb_dsn
