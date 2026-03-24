import json
import os
import re
from datetime import datetime

from app.core.config import Config
from app.core.managers.project_manager import ProjectManager
from app.core.utils.db_query import (
    delete_prompt_label_data,
    ensure_prompt_label_data,
    list_prompt_labels_data,
)


class PromptLabelManager:
    _POSTGRES_STORAGE_VALUES = {"postgres", "postgrel", "postgresql"}
    _DEFAULT_LABELS = ("Production", "Medical")
    _PROTECTED_LABELS = {"production"}
    _LABEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    LABELS_FILE = os.path.join(Config.UPLOAD_FOLDER, "prompt_labels.json")

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
    def normalize_label_name(cls, value: str | None) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return "Production"
        return normalized

    @classmethod
    def validate_label_name(cls, value: str | None) -> str:
        normalized = cls.normalize_label_name(value)
        if not cls._LABEL_NAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Invalid label name. Use letters/numbers with optional '-' or '_' (max 64 chars)."
            )
        return normalized

    @classmethod
    def initialize_labels(cls) -> None:
        ProjectManager.initialize_storage()
        if cls._use_postgres_storage():
            connection_string = cls._get_storage_connection_string()
            now = datetime.now().isoformat()
            for label in cls._DEFAULT_LABELS:
                ensure_prompt_label_data(connection_string, name=label, now_iso=now)
            return

        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        if not os.path.exists(cls.LABELS_FILE):
            now = datetime.now().isoformat()
            labels = [
                {
                    "name": label,
                    "created_at": now,
                    "updated_at": now,
                    "project_count": 0,
                }
                for label in cls._DEFAULT_LABELS
            ]
            cls._save_file_labels(labels)

    @classmethod
    def _load_file_labels(cls) -> list[dict[str, str]]:
        cls.initialize_labels()
        with open(cls.LABELS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        labels = data if isinstance(data, list) else []
        normalized_labels = []
        for item in labels:
            name = cls.normalize_label_name((item or {}).get("name"))
            if not name:
                continue
            normalized_labels.append(
                {
                    "name": name,
                    "created_at": str((item or {}).get("created_at") or ""),
                    "updated_at": str((item or {}).get("updated_at") or ""),
                    "project_count": int((item or {}).get("project_count") or 0),
                }
            )
        return normalized_labels

    @classmethod
    def _save_file_labels(cls, labels: list[dict[str, str]]) -> None:
        with open(cls.LABELS_FILE, "w", encoding="utf-8") as f:
            json.dump(labels, f, ensure_ascii=False, indent=2)

    @classmethod
    def list_labels(cls) -> list[dict[str, str]]:
        cls.initialize_labels()
        if cls._use_postgres_storage():
            return list_prompt_labels_data(cls._get_storage_connection_string())
        return sorted(cls._load_file_labels(), key=lambda item: item["name"].lower())

    @classmethod
    def ensure_label_exists(cls, name: str | None) -> str:
        normalized_name = cls.validate_label_name(name)
        if cls._use_postgres_storage():
            ensure_prompt_label_data(
                cls._get_storage_connection_string(),
                name=normalized_name,
                now_iso=datetime.now().isoformat(),
            )
            return normalized_name

        labels = cls._load_file_labels()
        if not any(item["name"].lower() == normalized_name.lower() for item in labels):
            now = datetime.now().isoformat()
            labels.append(
                {
                    "name": normalized_name,
                    "created_at": now,
                    "updated_at": now,
                    "project_count": 0,
                }
            )
            cls._save_file_labels(labels)
        return normalized_name

    @classmethod
    def create_label(cls, name: str | None) -> dict[str, str]:
        normalized_name = cls.ensure_label_exists(name)
        if cls._use_postgres_storage():
            labels = cls.list_labels()
            label = next((item for item in labels if item["name"] == normalized_name), None)
            if label is not None:
                return label
            return {
                "name": normalized_name,
                "created_at": "",
                "updated_at": "",
                "project_count": 0,
            }

        labels = cls._load_file_labels()
        label = next((item for item in labels if item["name"].lower() == normalized_name.lower()), None)
        if label is not None:
            return label
        return {
            "name": normalized_name,
            "created_at": "",
            "updated_at": "",
            "project_count": 0,
        }

    @classmethod
    def delete_label(cls, name: str) -> tuple[bool, str]:
        normalized_name = cls.normalize_label_name(name)
        if normalized_name.lower() in cls._PROTECTED_LABELS:
            return False, f"Label '{normalized_name}' is protected and cannot be deleted."

        if cls._use_postgres_storage():
            return delete_prompt_label_data(cls._get_storage_connection_string(), normalized_name)

        labels = cls._load_file_labels()
        if not any(item["name"].lower() == normalized_name.lower() for item in labels):
            return False, f"Prompt label not found: {normalized_name}"

        projects = ProjectManager.list_projects(limit=10000)
        in_use = any(
            str(getattr(project, "prompt_label", "")).strip().lower() == normalized_name.lower()
            for project in projects
        )
        if in_use:
            return False, f"Label '{normalized_name}' is used by project(s) and cannot be deleted."

        next_labels = [item for item in labels if item["name"].lower() != normalized_name.lower()]
        cls._save_file_labels(next_labels)
        return True, f"Prompt label deleted: {normalized_name}"
