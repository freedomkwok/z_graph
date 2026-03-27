import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import Config
from app.core.schemas.project import Project, ProjectStatus
from app.core.utils.db_query import (
    delete_project_data,
    ensure_postgres_schema,
    get_project_data,
    get_project_extracted_text,
    list_projects_data,
    upsert_project,
)


class ProjectManager:
    PROJECTS_DIR = os.path.join(Config.UPLOAD_FOLDER, "projects")
    SCHEMA_SQL_PATH = Path(__file__).resolve().parents[4] / "database" / "init_tables.sql"
    _POSTGRES_STORAGE_VALUES = {"postgres", "postgrel", "postgresql"}
    _postgres_storage_initialized = False

    @classmethod
    def _ensure_projects_dir(cls):
        os.makedirs(cls.PROJECTS_DIR, exist_ok=True)

    @classmethod
    def _get_project_dir(cls, project_id: str) -> str:
        return os.path.join(cls.PROJECTS_DIR, project_id)

    @classmethod
    def _get_project_meta_path(cls, project_id: str) -> str:
        return os.path.join(cls._get_project_dir(project_id), "project.json")

    @classmethod
    def _get_project_files_dir(cls, project_id: str) -> str:
        return os.path.join(cls._get_project_dir(project_id), "files")

    @classmethod
    def _get_project_text_path(cls, project_id: str) -> str:
        return os.path.join(cls._get_project_dir(project_id), "extracted_text.txt")

    @classmethod
    def _delete_project_dir(cls, project_id: str) -> None:
        project_dir = cls._get_project_dir(project_id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)

    @classmethod
    def _use_postgres_storage(cls) -> bool:
        return str(Config.STORAGE).strip().lower() in cls._POSTGRES_STORAGE_VALUES

    @classmethod
    def _get_storage_connection_string(cls) -> str:
        connection_string = (Config.PROJECT_STORAGE_CONNECTION_STRING or "").strip()
        if not connection_string:
            raise ValueError("PROJECT_STORAGE_CONNECTION_STRING is required when STORAGE=postgres")
        return connection_string

    @classmethod
    def _ensure_postgres_storage(cls) -> None:
        if cls._postgres_storage_initialized:
            return

        ensure_postgres_schema(
            connection_string=cls._get_storage_connection_string(),
            schema_sql_path=cls.SCHEMA_SQL_PATH,
        )
        cls._postgres_storage_initialized = True

    @classmethod
    def initialize_storage(cls) -> None:
        if cls._use_postgres_storage():
            cls._ensure_postgres_storage()
        else:
            cls._ensure_projects_dir()

    @classmethod
    def create_project(cls, name: str = "Unnamed Project", *, persist: bool = True) -> Project:
        cls.initialize_storage()

        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        project = Project(
            project_id=project_id,
            name=name,
            status=ProjectStatus.CREATED,
            created_at=now,
            updated_at=now,
        )

        project_dir = cls._get_project_dir(project_id)
        files_dir = cls._get_project_files_dir(project_id)
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(files_dir, exist_ok=True)

        if persist:
            cls.save_project(project)

        return project

    @classmethod
    def save_project(cls, project: Project) -> None:
        project.updated_at = datetime.now().isoformat()
        if cls._use_postgres_storage():
            cls._ensure_postgres_storage()
            upsert_project(
                cls._get_storage_connection_string(),
                project_id=project.project_id,
                created_at=project.created_at,
                updated_at=project.updated_at,
                project_data=project.to_dict(),
                zep_graph_id=project.zep_graph_id,
                project_workspace_id=project.project_workspace_id,
                zep_graph_address=project.zep_graph_address,
                prompt_label=project.prompt_label,
            )
            return

        meta_path = cls._get_project_meta_path(project.project_id)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def get_project(cls, project_id: str) -> Project | None:
        if cls._use_postgres_storage():
            cls._ensure_postgres_storage()
            project_data = get_project_data(cls._get_storage_connection_string(), project_id)
            if not project_data:
                return None
            return Project.from_dict(project_data)

        meta_path = cls._get_project_meta_path(project_id)

        if not os.path.exists(meta_path):
            return None

        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)

        return Project.from_dict(data)

    @classmethod
    def list_projects(cls, limit: int = 50) -> list[Project]:
        if cls._use_postgres_storage():
            cls._ensure_postgres_storage()
            rows = list_projects_data(cls._get_storage_connection_string(), limit)
            return [Project.from_dict(row) for row in rows]

        cls._ensure_projects_dir()

        projects = []
        for project_id in os.listdir(cls.PROJECTS_DIR):
            project = cls.get_project(project_id)
            if project:
                projects.append(project)

        projects.sort(key=lambda p: p.created_at, reverse=True)

        return projects[:limit]

    @classmethod
    def delete_project(cls, project_id: str) -> bool:
        if cls._use_postgres_storage():
            cls._ensure_postgres_storage()
            deleted = delete_project_data(cls._get_storage_connection_string(), project_id)
            cls._delete_project_dir(project_id)
            return deleted

        if not os.path.exists(cls._get_project_dir(project_id)):
            return False

        cls._delete_project_dir(project_id)
        return True

    @classmethod
    def save_file_to_project(
        cls, project_id: str, file_storage, original_filename: str
    ) -> dict[str, str]:
        files_dir = cls._get_project_files_dir(project_id)
        os.makedirs(files_dir, exist_ok=True)

        # Generate a safe filename
        ext = os.path.splitext(original_filename)[1].lower()
        safe_filename = f"{uuid.uuid4().hex[:8]}{ext}"
        file_path = os.path.join(files_dir, safe_filename)

        # Save file
        file_storage.save(file_path)

        # Get file size
        file_size = os.path.getsize(file_path)

        return {
            "original_filename": original_filename,
            "saved_filename": safe_filename,
            "path": file_path,
            "size": file_size,
        }

    @classmethod
    def save_extracted_text(cls, project_id: str, text: str) -> None:
        text_path = cls._get_project_text_path(project_id)
        with open(text_path, "w", encoding="utf-8") as f:
            f.write(text)

    @classmethod
    def get_extracted_text(cls, project_id: str) -> str | None:
        text_path = cls._get_project_text_path(project_id)

        if os.path.exists(text_path):
            with open(text_path, encoding="utf-8") as f:
                return f.read()

        if cls._use_postgres_storage():
            cls._ensure_postgres_storage()
            return get_project_extracted_text(cls._get_storage_connection_string(), project_id)

        return None

    @classmethod
    def get_project_files(cls, project_id: str) -> list[str]:
        files_dir = cls._get_project_files_dir(project_id)

        if not os.path.exists(files_dir):
            return []

        return [
            os.path.join(files_dir, f)
            for f in os.listdir(files_dir)
            if os.path.isfile(os.path.join(files_dir, f))
        ]
