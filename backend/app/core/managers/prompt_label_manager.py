import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import Config
from app.core.managers.project_manager import ProjectManager
from app.core.utils.db_query import (
    delete_prompt_label_data,
    ensure_prompt_label_data,
    get_prompt_label_stats_data,
    list_prompt_labels_data,
)


class PromptLabelManager:
    _POSTGRES_STORAGE_VALUES = {"postgres", "postgrel", "postgresql"}
    _DEFAULT_LABELS = ("Production", "Medical")
    _PROTECTED_LABELS = {"production"}
    _LABEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    LABELS_FILE = os.path.join(Config.UPLOAD_FOLDER, "prompt_labels.json")
    PROMPT_VERSIONING_DIR = Path(__file__).resolve().parents[1] / "langfuse_versioning"

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
    def _find_existing_label_case(
        cls,
        labels: list[dict[str, Any]],
        target_name: str,
    ) -> str | None:
        target_lower = target_name.lower()
        for item in labels:
            current_name = str((item or {}).get("name") or "").strip()
            if current_name and current_name.lower() == target_lower:
                return current_name
        return None

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
    def get_label_stats(cls) -> dict[str, Any]:
        cls.initialize_labels()
        if cls._use_postgres_storage():
            return get_prompt_label_stats_data(cls._get_storage_connection_string())

        labels = cls._load_file_labels()
        updated_at = max((str(item.get("updated_at") or "") for item in labels), default="")
        return {
            "total_labels": len(labels),
            "updated_at": updated_at,
        }

    @classmethod
    def ensure_label_exists(cls, name: str | None) -> str:
        cls.initialize_labels()
        normalized_name = cls.validate_label_name(name)
        now_iso = datetime.now().isoformat()
        if cls._use_postgres_storage():
            connection_string = cls._get_storage_connection_string()
            existing_name = cls._find_existing_label_case(
                list_prompt_labels_data(connection_string),
                normalized_name,
            )
            resolved_name = existing_name or normalized_name
            ensure_prompt_label_data(
                connection_string,
                name=resolved_name,
                now_iso=now_iso,
            )
            return resolved_name

        labels = cls._load_file_labels()
        existing_name = cls._find_existing_label_case(labels, normalized_name)
        if existing_name:
            return existing_name
        if not any(item["name"].lower() == normalized_name.lower() for item in labels):
            labels.append(
                {
                    "name": normalized_name,
                    "created_at": now_iso,
                    "updated_at": now_iso,
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
        cls.initialize_labels()
        normalized_name = cls.normalize_label_name(name)
        if normalized_name.lower() in cls._PROTECTED_LABELS:
            return False, f"Label '{normalized_name}' is protected and cannot be deleted."

        if cls._use_postgres_storage():
            connection_string = cls._get_storage_connection_string()
            existing_name = cls._find_existing_label_case(
                list_prompt_labels_data(connection_string),
                normalized_name,
            )
            if existing_name is None:
                return False, f"Prompt label not found: {normalized_name}"
            return delete_prompt_label_data(connection_string, existing_name)

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

    @classmethod
    def sync_label_from_langfuse(
        cls,
        label_name: str,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        # Keep label creation independent from folder creation;
        # folders are materialized only by pull/sync.
        resolved_label = cls.ensure_label_exists(label_name)

        public_key = Config.LANGFUSE_PUBLIC_KEY or os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = Config.LANGFUSE_SECRET_KEY or os.getenv("LANGFUSE_SECRET_KEY")
        base_url = (
            Config.LANGFUSE_BASE_URL
            or Config.LANGFUSE_HOST
            or os.getenv("LANGFUSE_BASE_URL")
            or os.getenv("LANGFUSE_HOST")
            or ""
        )
        if not public_key or not secret_key:
            raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")
        if not str(base_url).strip():
            raise ValueError("LANGFUSE_BASE_URL (or LANGFUSE_HOST) is required")

        from scripts.sync_from_langfuse import (
            download_prompts_from_langfuse,
            normalize_label,
        )

        result = download_prompts_from_langfuse(
            output_root=cls.PROMPT_VERSIONING_DIR,
            public_key=public_key,
            secret_key=secret_key,
            base_url=str(base_url).strip(),
            requested_label=normalize_label(resolved_label),
            dry_run=dry_run,
        )

        # Ensure any labels discovered from Langfuse also exist in label catalog.
        downloaded_labels: list[str] = []
        for downloaded_label in result.get("downloaded_labels", []):
            if downloaded_label:
                downloaded_labels.append(cls.ensure_label_exists(downloaded_label))

        result["requested_label"] = resolved_label
        result["downloaded_labels"] = sorted(set(downloaded_labels), key=str.lower)
        result["label_stats"] = cls.get_label_stats()
        return result
