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
    _INTERNAL_LABELS = {"latest"}
    _LABEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    _LABEL_TYPE_FILE_MAP = {
        "individual": ("ENTITY_EXAMPLES_IN_SYSTEM_PROMPT.md",),
        "individual_exception": ("ENTITT_EXCEPTIONS_IN_SYSTEM_PROMPT.md",),
        "organization": ("ORGANIZATION_EXAMPLES_IN_SYSTEM_PROMPT.md",),
        "organization_exception": ("ORGANIZATION_EXCEPTIONS_IN_SYSTEM_PROMPT.md",),
        "relationship": ("RELATIONS_IN_SYSTEM_PROMPT copy.md", "RELATIONS_IN_SYSTEM_PROMPT.md"),
        "relationship_exception": ("RELATIONS_EXPCETIONS_IN_SYSTEM_PROMPT.md",),
    }
    _LABEL_TYPE_CONFLICT_PAIRS = (
        ("individual", "individual_exception"),
        ("organization", "organization_exception"),
        ("relationship", "relationship_exception"),
    )
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
    def _is_internal_label(cls, name: str | None) -> bool:
        normalized = str(name or "").strip().lower()
        return bool(normalized and normalized in cls._INTERNAL_LABELS)

    @classmethod
    def _filter_user_labels(cls, labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in labels:
            name = str((item or {}).get("name") or "").strip()
            if not name:
                continue
            if cls._is_internal_label(name):
                continue
            filtered.append(item)
        return filtered

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
            labels = list_prompt_labels_data(cls._get_storage_connection_string())
            labels = cls._filter_user_labels(labels)
            return sorted(labels, key=lambda item: str(item.get("name", "")).lower())
        labels = cls._filter_user_labels(cls._load_file_labels())
        return sorted(labels, key=lambda item: item["name"].lower())

    @classmethod
    def get_label_stats(cls) -> dict[str, Any]:
        cls.initialize_labels()
        if cls._use_postgres_storage():
            labels = cls._filter_user_labels(
                list_prompt_labels_data(cls._get_storage_connection_string())
            )
            updated_at = max((str(item.get("updated_at") or "") for item in labels), default="")
            return {
                "total_labels": len(labels),
                "updated_at": updated_at,
            }

        labels = cls._filter_user_labels(cls._load_file_labels())
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
                return False, f"Category label not found: {normalized_name}"
            return delete_prompt_label_data(connection_string, existing_name)

        labels = cls._load_file_labels()
        if not any(item["name"].lower() == normalized_name.lower() for item in labels):
            return False, f"Category label not found: {normalized_name}"

        projects = ProjectManager.list_projects(limit=10000)
        in_use = any(
            str(getattr(project, "prompt_label", "")).strip().lower() == normalized_name.lower()
            for project in projects
        )
        if in_use:
            return False, f"Label '{normalized_name}' is used by project(s) and cannot be deleted."

        next_labels = [item for item in labels if item["name"].lower() != normalized_name.lower()]
        cls._save_file_labels(next_labels)
        return True, f"Category label deleted: {normalized_name}"

    @classmethod
    def _normalize_label_folder_name(cls, label_name: str | None) -> str:
        normalized = str(label_name or "").strip().lower()
        return normalized or "production"

    @classmethod
    def _build_label_type_file_candidates(
        cls,
        *,
        label_name: str,
        file_names: tuple[str, ...],
    ) -> list[Path]:
        normalized_label = cls._normalize_label_folder_name(label_name)
        ontology_labels_dir = cls.PROMPT_VERSIONING_DIR / "ontology_section" / "labels"
        # Keep old folder candidates for backward compatibility.
        legacy_prompts_dir = cls.PROMPT_VERSIONING_DIR / "prompts"
        candidates: list[Path] = []
        for file_name in file_names:
            next_candidates = [
                ontology_labels_dir / normalized_label / file_name,
                ontology_labels_dir / "production" / file_name,
                legacy_prompts_dir / normalized_label / file_name,
                legacy_prompts_dir / "production" / file_name,
                legacy_prompts_dir / file_name,
            ]
            for candidate in next_candidates:
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    @classmethod
    def _parse_string_list_content(cls, value: str) -> list[str]:
        parsed_items: list[str] = []
        seen: set[str] = set()
        for raw_line in str(value or "").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("- ") or stripped.startswith("* "):
                stripped = stripped[2:].strip()
            dedupe_key = stripped.lower()
            if not stripped or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            parsed_items.append(stripped)
        return parsed_items

    @classmethod
    def _normalize_string_list_payload(cls, values: Any, *, field_name: str) -> list[str]:
        if not isinstance(values, list):
            raise ValueError(f"{field_name} must be a list of strings")

        normalized_values: list[str] = []
        seen: set[str] = set()
        for raw_value in values:
            normalized = str(raw_value or "").strip()
            if not normalized:
                continue
            dedupe_key = normalized.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized_values.append(normalized)
        return normalized_values

    @classmethod
    def _serialize_string_list_content(cls, values: list[str]) -> str:
        if not values:
            return ""
        return "\n".join(f"- {value}" for value in values) + "\n"

    @classmethod
    def _touch_label_updated_at(cls, label_name: str) -> None:
        now_iso = datetime.now().isoformat()
        if cls._use_postgres_storage():
            ensure_prompt_label_data(
                cls._get_storage_connection_string(),
                name=label_name,
                now_iso=now_iso,
            )
            return

        labels = cls._load_file_labels()
        normalized_target = label_name.lower()
        found = False
        for item in labels:
            current_name = str((item or {}).get("name") or "").strip()
            if current_name.lower() != normalized_target:
                continue
            item["updated_at"] = now_iso
            found = True
            break
        if not found:
            labels.append(
                {
                    "name": label_name,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "project_count": 0,
                }
            )
        cls._save_file_labels(labels)

    @classmethod
    def get_label_type_lists(cls, label_name: str) -> dict[str, Any]:
        resolved_label = cls.ensure_label_exists(label_name)
        resolved_types: dict[str, list[str]] = {}
        source_paths: dict[str, str] = {}

        for type_name, file_names in cls._LABEL_TYPE_FILE_MAP.items():
            selected_source = ""
            content = ""
            for candidate in cls._build_label_type_file_candidates(
                label_name=resolved_label,
                file_names=file_names,
            ):
                if not candidate.exists():
                    continue
                content = candidate.read_text(encoding="utf-8")
                selected_source = candidate.relative_to(cls.PROMPT_VERSIONING_DIR).as_posix()
                break

            resolved_types[type_name] = cls._parse_string_list_content(content)
            source_paths[type_name] = selected_source

        return {
            "label_name": resolved_label,
            "types": resolved_types,
            "sources": source_paths,
        }

    @classmethod
    def update_label_type_lists(cls, label_name: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        resolved_label = cls.ensure_label_exists(label_name)
        normalized_label = cls._normalize_label_folder_name(resolved_label)
        target_dir = cls.PROMPT_VERSIONING_DIR / "ontology_section" / "labels" / normalized_label
        target_dir.mkdir(parents=True, exist_ok=True)

        normalized_types: dict[str, list[str]] = {}
        for type_name in cls._LABEL_TYPE_FILE_MAP:
            normalized_types[type_name] = cls._normalize_string_list_payload(
                payload.get(type_name, []),
                field_name=type_name,
            )

        for left_field, right_field in cls._LABEL_TYPE_CONFLICT_PAIRS:
            left_values = normalized_types.get(left_field, [])
            right_values = normalized_types.get(right_field, [])
            right_lookup = {value.lower(): value for value in right_values}
            overlaps = [value for value in left_values if value.lower() in right_lookup]
            if overlaps:
                joined = ", ".join(overlaps)
                raise ValueError(
                    f"Duplicate values are not allowed between {left_field} and {right_field}: {joined}"
                )

        for type_name, file_names in cls._LABEL_TYPE_FILE_MAP.items():
            primary_file_name = file_names[0]
            target_file = target_dir / primary_file_name
            serialized = cls._serialize_string_list_content(normalized_types[type_name])
            target_file.write_text(serialized, encoding="utf-8")

        cls._touch_label_updated_at(resolved_label)
        return cls.get_label_type_lists(resolved_label)

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
                if cls._is_internal_label(downloaded_label):
                    continue
                downloaded_labels.append(cls.ensure_label_exists(downloaded_label))

        result["requested_label"] = resolved_label
        result["downloaded_labels"] = sorted(set(downloaded_labels), key=str.lower)
        result["label_stats"] = cls.get_label_stats()
        return result
