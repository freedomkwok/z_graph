import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from app.core.config import Config
from app.core.langfuse_versioning.langfuse_category_label_retriever import (
    build_label_fallback_candidates,
    normalize_label as normalize_langfuse_label,
)
from app.core.langfuse_versioning.prompt_provider import is_prompt_versioning, make_prompt_provider
from app.core.managers.project_manager import ProjectManager
from app.core.utils.db_query import (
    delete_prompt_label_data,
    ensure_prompt_label_data,
    get_prompt_label_stats_data,
    list_prompt_labels_data,
)

logger = logging.getLogger("uvicorn.error")


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
        "relationship": ("RELATIONS_IN_SYSTEM_PROMPT.md", "RELATIONS_IN_SYSTEM_PROMPT copy.md"),
        "relationship_exception": ("RELATIONS_EXPCETIONS_IN_SYSTEM_PROMPT.md",),
    }
    _LABEL_TYPE_PRIMARY_FILE_MAP = {
        "individual": "ENTITY_EXAMPLES_IN_SYSTEM_PROMPT.md",
        "individual_exception": "ENTITT_EXCEPTIONS_IN_SYSTEM_PROMPT.md",
        "organization": "ORGANIZATION_EXAMPLES_IN_SYSTEM_PROMPT.md",
        "organization_exception": "ORGANIZATION_EXCEPTIONS_IN_SYSTEM_PROMPT.md",
        "relationship": "RELATIONS_IN_SYSTEM_PROMPT.md",
        "relationship_exception": "RELATIONS_EXPCETIONS_IN_SYSTEM_PROMPT.md",
    }
    _LABEL_TYPE_LANGFUSE_PROMPT_MAP = {
        "individual": "ontology_section/labels/ENTITY_EXAMPLES_IN_SYSTEM_PROMPT",
        "individual_exception": "ontology_section/labels/ENTITT_EXCEPTIONS_IN_SYSTEM_PROMPT",
        "organization": "ontology_section/labels/ORGANIZATION_EXAMPLES_IN_SYSTEM_PROMPT",
        "organization_exception": "ontology_section/labels/ORGANIZATION_EXCEPTIONS_IN_SYSTEM_PROMPT",
        "relationship": "ontology_section/labels/RELATIONS_IN_SYSTEM_PROMPT",
        "relationship_exception": "ontology_section/labels/RELATIONS_EXPCETIONS_IN_SYSTEM_PROMPT",
    }
    _LABEL_TYPE_CONFLICT_PAIRS = (
        ("individual", "individual_exception"),
        ("organization", "organization_exception"),
        ("relationship", "relationship_exception"),
    )
    _REQUIRED_LABEL_TYPE_VALUES_FALLBACK = {
        "individual": [
            "Student: student",
            "Professor: professor or scholar",
            "Journalist: journalist",
            "Celebrity: celebrity or influencer",
            "Executive",
            "Official: government official",
            "Lawyer: lawyer",
            "Doctor: doctor",
        ],
        "individual_exception": [
            "Person",
        ],
        "organization": [
            "University: higher education institution",
            "Company: business organization",
            "GovernmentAgency: government agency",
            "MediaOutlet: media organization",
            "Hospital: hospital",
            "School: primary or secondary school",
        ],
        "organization_exception": [
            "Organization: any organization",
        ],
        "relationship": [
            "WORKS_FOR: works for",
            "STUDIES_AT: studies at",
            "AFFILIATED_WITH: affiliated with",
            "REPRESENTS: represents",
            "REGULATES: regulates",
            "REPORTS_ON: reports on",
            "COMMENTS_ON: comments on",
            "RESPONDS_TO: responds to",
            "SUPPORTS: supports",
            "OPPOSES: opposes",
            "COLLABORATES_WITH: collaborates with",
            "COMPETES_WITH: competes with",
        ],
        "relationship_exception": [
            "RELATED_TO: related",
        ],
    }
    _BASE_PROMPT_FILE_MAP = {
        "ontology_prompt": {
            "file_name": "ONTOLOGY_SYSTEM_PROMPT.md",
            "provider_name": "ontology_section/prompts/ONTOLOGY_SYSTEM_PROMPT.md",
            "langfuse_prompt_name": "ontology_section/prompts/ONTOLOGY_SYSTEM_PROMPT",
            "scope": "label",
        },
        "ontology_output_extraction": {
            "file_name": "USER_EXTRACTION_PROMPT.md",
            "provider_name": "ontology_section/prompts/USER_EXTRACTION_PROMPT.md",
            "langfuse_prompt_name": "ontology_section/prompts/USER_EXTRACTION_PROMPT",
            "scope": "label",
        },
        "entity_edge_generator_prompt": {
            "file_name": "ENTITY_EDGE_GENERATOR.md",
            "provider_name": "auto_label_generator/prompts/production/ENTITY_EDGE_GENERATOR.md",
            "langfuse_prompt_name": "auto_label_generator/prompts/production/ENTITY_EDGE_GENERATOR",
            "scope": "global",
            "provider_label": "production",
            "langfuse_label": "production",
            "relative_dir": "auto_label_generator/prompts/production",
        },
    }
    _PROMPT_TEMPLATE_REQUIRED_VARIABLES = {
        "ontology_output_extraction": ("combined_text",),
        "entity_edge_generator_prompt": ("label_name", "combined_text"),
    }
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
    def get_project_label_info(
        cls,
        *,
        label_name: str | None,
        project_id: str | None,
    ) -> dict[str, Any]:
        normalized_label_name = cls.normalize_label_name(label_name)
        normalized_project_id = str(project_id or "").strip()

        matched_label: dict[str, Any] | None = None
        for item in cls.list_labels():
            candidate_name = str((item or {}).get("name") or "").strip()
            if not candidate_name:
                continue
            if candidate_name.lower() != normalized_label_name.lower():
                continue
            matched_label = item
            break

        matched_name = str((matched_label or {}).get("name") or normalized_label_name).strip()
        matched_project_id = str((matched_label or {}).get("project_id") or "").strip()
        is_project_scoped = bool(
            matched_project_id
            and normalized_project_id
            and matched_project_id.lower() == normalized_project_id.lower()
        )

        return {
            "name": matched_name or "Production",
            "project_id": matched_project_id or None,
            "is_project_scoped": is_project_scoped,
            "is_global": not bool(matched_project_id),
        }

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
    def _normalize_prompt_template_key(cls, key: str | None) -> str:
        normalized = str(key or "").strip().lower()
        if normalized not in cls._BASE_PROMPT_FILE_MAP:
            raise ValueError(
                "Unsupported prompt key. Expected one of: ontology_prompt, ontology_output_extraction, entity_edge_generator_prompt"
            )
        return normalized

    @classmethod
    def _get_prompt_template_meta(cls, key: str | None) -> dict[str, str]:
        normalized_key = cls._normalize_prompt_template_key(key)
        return cls._BASE_PROMPT_FILE_MAP[normalized_key]

    @classmethod
    def _build_prompt_template_local_path(
        cls,
        *,
        label_name: str,
        prompt_key: str,
    ) -> Path:
        prompt_meta = cls._get_prompt_template_meta(prompt_key)
        scope = str(prompt_meta.get("scope") or "label").strip().lower()
        if scope == "global":
            relative_dir = str(prompt_meta.get("relative_dir") or "").strip().strip("/")
            if not relative_dir:
                raise ValueError(f"Prompt key '{prompt_key}' is missing relative_dir metadata")
            return (
                cls.PROMPT_VERSIONING_DIR
                / relative_dir
                / prompt_meta["file_name"]
            )

        normalized_label = cls._normalize_label_folder_name(label_name)
        return (
            cls.PROMPT_VERSIONING_DIR
            / "ontology_section"
            / "prompts"
            / normalized_label
            / prompt_meta["file_name"]
        )

    @classmethod
    def _resolve_prompt_template_provider_label(
        cls,
        prompt_meta: dict[str, str],
        *,
        resolved_label: str,
    ) -> str | None:
        scope = str(prompt_meta.get("scope") or "label").strip().lower()
        if scope == "global":
            configured = normalize_langfuse_label(str(prompt_meta.get("provider_label") or ""))
            return configured or "production"
        return cls._normalize_label_folder_name(resolved_label)

    @classmethod
    def _resolve_prompt_template_langfuse_label(
        cls,
        prompt_meta: dict[str, str],
        *,
        resolved_label: str,
    ) -> str:
        """Resolve Langfuse write label with a safe production fallback."""
        scope = str(prompt_meta.get("scope") or "label").strip().lower()
        if scope == "global":
            configured = normalize_langfuse_label(str(prompt_meta.get("langfuse_label") or ""))
            return configured or "production"
        resolved = normalize_langfuse_label(resolved_label)
        return resolved or "production"

    @classmethod
    def _validate_prompt_template_content(cls, prompt_key: str, content: str) -> None:
        required_variables = cls._PROMPT_TEMPLATE_REQUIRED_VARIABLES.get(prompt_key, ())
        if not required_variables:
            return
        normalized_content = str(content or "")
        missing_variables = []
        for variable_name in required_variables:
            token = f"{{{{{variable_name}}}}}"
            if token in normalized_content:
                continue
            token_with_spaces = f"{{{{ {variable_name} }}}}"
            if token_with_spaces in normalized_content:
                continue
            missing_variables.append(variable_name)
        if missing_variables:
            joined = ", ".join(missing_variables)
            raise ValueError(
                f"{prompt_key} prompt must include required template variable(s): {joined}"
            )

    @classmethod
    def get_label_prompt_template(cls, label_name: str, prompt_key: str) -> dict[str, Any]:
        resolved_label = cls.ensure_label_exists(label_name)
        normalized_key = cls._normalize_prompt_template_key(prompt_key)
        prompt_meta = cls._get_prompt_template_meta(normalized_key)
        provider_label = cls._resolve_prompt_template_provider_label(
            prompt_meta,
            resolved_label=resolved_label,
        )

        provider = make_prompt_provider(prompts_dir=cls.PROMPT_VERSIONING_DIR)
        content = provider.get(prompt_meta["provider_name"], label=provider_label)

        local_path = cls._build_prompt_template_local_path(
            label_name=resolved_label,
            prompt_key=normalized_key,
        )
        source = ""
        if local_path.exists():
            source = local_path.relative_to(cls.PROMPT_VERSIONING_DIR).as_posix()

        return {
            "label_name": resolved_label,
            "prompt_key": normalized_key,
            "content": content,
            "source": source,
        }

    @classmethod
    def update_label_prompt_template(
        cls,
        *,
        label_name: str,
        prompt_key: str,
        content: Any,
    ) -> dict[str, Any]:
        resolved_label = cls.ensure_label_exists(label_name)
        normalized_key = cls._normalize_prompt_template_key(prompt_key)
        prompt_meta = cls._get_prompt_template_meta(normalized_key)
        normalized_content = str(content or "")
        cls._validate_prompt_template_content(normalized_key, normalized_content)

        if cls._is_langfuse_prompt_backend():
            public_key, secret_key, base_url = cls._resolve_langfuse_connection()
            local_path = cls._build_prompt_template_local_path(
                label_name=resolved_label,
                prompt_key=normalized_key,
            )
            source_path = f"app/core/langfuse_versioning/{local_path.relative_to(cls.PROMPT_VERSIONING_DIR).as_posix()}"
            langfuse_label = cls._resolve_prompt_template_langfuse_label(
                prompt_meta,
                resolved_label=resolved_label,
            )
            with httpx.Client(auth=(public_key, secret_key), timeout=20.0) as client:
                cls._upsert_langfuse_prompt(
                    client=client,
                    base_url=base_url,
                    prompt_name=prompt_meta["langfuse_prompt_name"],
                    label=langfuse_label,
                    content=normalized_content,
                    source_path=source_path,
                )
            cls._touch_label_updated_at(resolved_label)
            return cls.get_label_prompt_template(resolved_label, normalized_key)

        local_path = cls._build_prompt_template_local_path(
            label_name=resolved_label,
            prompt_key=normalized_key,
        )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(normalized_content, encoding="utf-8")
        cls._touch_label_updated_at(resolved_label)
        return cls.get_label_prompt_template(resolved_label, normalized_key)

    @classmethod
    def sync_label_prompt_template_from_default(
        cls,
        *,
        label_name: str,
        prompt_key: str,
    ) -> dict[str, Any]:
        resolved_label = cls.ensure_label_exists(label_name)
        normalized_key = cls._normalize_prompt_template_key(prompt_key)
        default_payload = cls.get_label_prompt_template("Production", normalized_key)
        default_content = str(default_payload.get("content") or "")
        return cls.update_label_prompt_template(
            label_name=resolved_label,
            prompt_key=normalized_key,
            content=default_content,
        )

    @classmethod
    def _build_label_type_file_candidates(
        cls,
        *,
        label_name: str,
        file_names: tuple[str, ...],
    ) -> list[Path]:
        normalized_label = cls._normalize_label_folder_name(label_name)
        ontology_labels_dir = cls.PROMPT_VERSIONING_DIR / "ontology_section" / "labels"
        candidates: list[Path] = []
        for file_name in file_names:
            next_candidates = [
                ontology_labels_dir / normalized_label / file_name,
                ontology_labels_dir / "production" / file_name,
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
    def _remove_cross_pair_duplicates(
        cls,
        values_by_type: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        # Keep primary lists intact and filter overlaps from paired exception lists.
        # This protects UI/default retrieval when synced files are inconsistent.
        for left_field, right_field in cls._LABEL_TYPE_CONFLICT_PAIRS:
            left_values = values_by_type.get(left_field, [])
            right_values = values_by_type.get(right_field, [])
            if not left_values or not right_values:
                continue

            left_lookup = {str(value).strip().lower() for value in left_values if str(value).strip()}
            if not left_lookup:
                continue

            filtered_right = [
                value
                for value in right_values
                if str(value).strip() and str(value).strip().lower() not in left_lookup
            ]
            values_by_type[right_field] = filtered_right

        return values_by_type

    @classmethod
    def _get_required_label_type_values(cls) -> dict[str, list[str]]:
        required: dict[str, list[str]] = {}
        production_label = "production"
        ontology_labels_dir = cls.PROMPT_VERSIONING_DIR / "ontology_section" / "labels" / production_label

        for type_name, primary_file_name in cls._LABEL_TYPE_PRIMARY_FILE_MAP.items():
            source_file = ontology_labels_dir / primary_file_name
            if source_file.exists():
                parsed = cls._parse_string_list_content(source_file.read_text(encoding="utf-8"))
                if parsed:
                    required[type_name] = parsed
                    continue
            required[type_name] = list(cls._REQUIRED_LABEL_TYPE_VALUES_FALLBACK.get(type_name, []))

        return required

    @classmethod
    def _validate_required_label_type_values(
        cls,
        values_by_type: dict[str, list[str]],
    ) -> None:
        required_by_type = cls._get_required_label_type_values()
        for type_name, required_values in required_by_type.items():
            if not required_values:
                continue
            current_values = list(values_by_type.get(type_name, []))
            missing_required_values = [
                required_value for required_value in required_values if required_value not in current_values
            ]
            if missing_required_values:
                joined_missing = ", ".join(missing_required_values)
                raise ValueError(
                    f"{type_name} is missing required default value(s): {joined_missing}"
                )

    @classmethod
    def _is_langfuse_prompt_backend(cls) -> bool:
        return bool(is_prompt_versioning())

    @classmethod
    def _resolve_langfuse_connection(cls) -> tuple[str, str, str]:
        public_key = str(Config.LANGFUSE_PUBLIC_KEY or os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
        secret_key = str(Config.LANGFUSE_SECRET_KEY or os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
        base_url = str(
            Config.LANGFUSE_BASE_URL
            or Config.LANGFUSE_HOST
            or os.getenv("LANGFUSE_BASE_URL")
            or os.getenv("LANGFUSE_HOST")
            or ""
        ).strip()

        if not public_key or not secret_key:
            raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")
        if not base_url:
            raise ValueError("LANGFUSE_BASE_URL (or LANGFUSE_HOST) is required")
        return public_key, secret_key, base_url.rstrip("/")

    @classmethod
    def _extract_langfuse_prompt_text(cls, payload: Any) -> str | None:
        if isinstance(payload, str):
            return payload

        if isinstance(payload, dict):
            for key in ("prompt", "text", "content", "template"):
                if key not in payload:
                    continue
                value = payload.get(key)
                if isinstance(value, str):
                    return value
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False, indent=2)

            for key in ("data", "item", "result"):
                if key not in payload:
                    continue
                nested = cls._extract_langfuse_prompt_text(payload.get(key))
                if nested is not None:
                    return nested

            versions = payload.get("versions")
            if isinstance(versions, list):
                for version_item in versions:
                    nested = cls._extract_langfuse_prompt_text(version_item)
                    if nested is not None:
                        return nested

            latest_version = payload.get("latestVersion")
            if latest_version is not None:
                nested = cls._extract_langfuse_prompt_text(latest_version)
                if nested is not None:
                    return nested

        if isinstance(payload, list):
            for item in payload:
                nested = cls._extract_langfuse_prompt_text(item)
                if nested is not None:
                    return nested

        return None

    @classmethod
    def _fetch_langfuse_prompt_text(
        cls,
        *,
        client: httpx.Client,
        base_url: str,
        prompt_name: str,
        label: str | None,
    ) -> str | None:
        endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts/{quote(prompt_name, safe='')}"
        params: dict[str, str] = {}
        normalized_label = normalize_langfuse_label(label)
        if normalized_label:
            params["label"] = normalized_label

        response = client.get(endpoint, params=params or None)
        if response.status_code == 404:
            return None
        response.raise_for_status()

        text = cls._extract_langfuse_prompt_text(response.json())
        if text is None:
            raise ValueError(f"Langfuse prompt payload has no text: {prompt_name}")
        return text

    @classmethod
    def _upsert_langfuse_prompt(
        cls,
        *,
        client: httpx.Client,
        base_url: str,
        prompt_name: str,
        label: str,
        content: str,
        source_path: str,
    ) -> None:
        endpoint = f"{base_url.rstrip('/')}/api/public/v2/prompts"
        payload = {
            "name": prompt_name,
            "type": "text",
            "prompt": content,
            "labels": [label],
            "config": {"sourcePath": source_path},
        }
        response = client.post(endpoint, json=payload)
        if response.status_code in (200, 201, 409):
            return
        raise RuntimeError(
            "Langfuse prompt upsert failed for "
            f"'{prompt_name}' label='{label}': {response.status_code} {response.text[:240]}"
        )

    @classmethod
    def _get_label_type_lists_from_langfuse(cls, resolved_label: str) -> dict[str, Any]:
        normalized_label = cls._normalize_label_folder_name(resolved_label)
        label_candidates = build_label_fallback_candidates(
            requested_label=normalized_label,
            default_label="production",
        )
        public_key, secret_key, base_url = cls._resolve_langfuse_connection()

        resolved_types: dict[str, list[str]] = {}
        source_paths: dict[str, str] = {}
        with httpx.Client(auth=(public_key, secret_key), timeout=20.0) as client:
            for type_name, prompt_name in cls._LABEL_TYPE_LANGFUSE_PROMPT_MAP.items():
                content = ""
                selected_source = ""
                for label_candidate in label_candidates:
                    try:
                        fetched = cls._fetch_langfuse_prompt_text(
                            client=client,
                            base_url=base_url,
                            prompt_name=prompt_name,
                            label=label_candidate,
                        )
                    except httpx.HTTPError as exc:
                        raise RuntimeError(
                            f"Failed to read Langfuse prompt '{prompt_name}' for label '{label_candidate}': {exc}"
                        ) from exc
                    if fetched is None:
                        continue
                    content = fetched
                    selected_label = normalize_langfuse_label(label_candidate) or "none"
                    selected_source = f"langfuse:{prompt_name}#label={selected_label}"
                    break

                resolved_types[type_name] = cls._parse_string_list_content(content)
                source_paths[type_name] = selected_source

        resolved_types = cls._remove_cross_pair_duplicates(resolved_types)
        return {
            "label_name": resolved_label,
            "types": resolved_types,
            "sources": source_paths,
        }

    @classmethod
    def _update_label_type_lists_in_langfuse(
        cls,
        *,
        label_name: str,
        normalized_types: dict[str, list[str]],
    ) -> dict[str, str]:
        normalized_label = cls._normalize_label_folder_name(label_name)
        public_key, secret_key, base_url = cls._resolve_langfuse_connection()

        source_paths: dict[str, str] = {}
        with httpx.Client(auth=(public_key, secret_key), timeout=20.0) as client:
            for type_name, prompt_name in cls._LABEL_TYPE_LANGFUSE_PROMPT_MAP.items():
                content = cls._serialize_string_list_content(normalized_types.get(type_name, []))
                source_path = (
                    "app/core/langfuse_versioning/ontology_section/labels/"
                    f"{normalized_label}/{cls._LABEL_TYPE_PRIMARY_FILE_MAP[type_name]}"
                )
                try:
                    cls._upsert_langfuse_prompt(
                        client=client,
                        base_url=base_url,
                        prompt_name=prompt_name,
                        label=normalized_label,
                        content=content,
                        source_path=source_path,
                    )
                except httpx.HTTPError as exc:
                    raise RuntimeError(
                        f"Failed to write Langfuse prompt '{prompt_name}' for label '{normalized_label}': {exc}"
                    ) from exc
                source_paths[type_name] = f"langfuse:{prompt_name}#label={normalized_label}"

        return source_paths

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
        if cls._is_langfuse_prompt_backend():
            try:
                return cls._get_label_type_lists_from_langfuse(resolved_label)
            except Exception as exc:
                logger.warning(
                    "Langfuse label type read failed for '%s'; fallback to local files. Error=%s",
                    resolved_label,
                    str(exc),
                )

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

        resolved_types = cls._remove_cross_pair_duplicates(resolved_types)

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

        # Persist exactly what frontend sends (after normalization and conflict checks).
        # Do not force legacy production defaults back into user-managed label lists.

        if cls._is_langfuse_prompt_backend():
            source_paths = cls._update_label_type_lists_in_langfuse(
                label_name=resolved_label,
                normalized_types=normalized_types,
            )
            resolved_types = {type_name: list(values) for type_name, values in normalized_types.items()}
            resolved_types = cls._remove_cross_pair_duplicates(resolved_types)
            cls._touch_label_updated_at(resolved_label)
            return {
                "label_name": resolved_label,
                "types": resolved_types,
                "sources": source_paths,
            }

        normalized_label = cls._normalize_label_folder_name(resolved_label)
        target_dir = cls.PROMPT_VERSIONING_DIR / "ontology_section" / "labels" / normalized_label
        target_dir.mkdir(parents=True, exist_ok=True)

        for type_name, file_names in cls._LABEL_TYPE_FILE_MAP.items():
            primary_file_name = file_names[0]
            target_file = target_dir / primary_file_name
            serialized = cls._serialize_string_list_content(normalized_types[type_name])
            target_file.write_text(serialized, encoding="utf-8")

        cls._touch_label_updated_at(resolved_label)
        return cls.get_label_type_lists(resolved_label)

    @classmethod
    def generate_label_type_lists_from_documents(
        cls,
        label_name: str,
        *,
        document_texts: list[str],
        project_id: str | None = None,
        entity_edge_generator_prompt_content: Any = None,
    ) -> dict[str, Any]:
        resolved_label = cls.validate_label_name(label_name)
        existing_name = cls._find_existing_label_case(cls.list_labels(), resolved_label)
        if existing_name:
            resolved_label = existing_name
        normalized_documents = [
            str(document_text).strip()
            for document_text in document_texts
            if str(document_text).strip()
        ]
        if not normalized_documents:
            raise ValueError("No document text available for LLM generation")

        from app.core.service.auto_label_generator import AutoLabelGenerator

        generator = AutoLabelGenerator()
        normalized_entity_edge_generator_prompt_content = (
            str(entity_edge_generator_prompt_content).strip()
            if isinstance(entity_edge_generator_prompt_content, str)
            and str(entity_edge_generator_prompt_content).strip()
            else None
        )
        generated_payload = generator.generate(
            document_texts=normalized_documents,
            label_name=resolved_label,
            project_id=project_id,
            entity_edge_generator_prompt_content=normalized_entity_edge_generator_prompt_content,
        )
        generated_types = {
            type_name: list(generated_payload.get(type_name, []))
            for type_name in cls._LABEL_TYPE_FILE_MAP
        }
        generated_types = cls._remove_cross_pair_duplicates(generated_types)
        generated_summary = str(generated_payload.get("document_summary") or "").strip()

        return {
            "label_name": resolved_label,
            "types": generated_types,
            "document_summary": generated_summary,
            "sources": {
                "generator_prompt": AutoLabelGenerator.PROMPT_TEMPLATE_NAME,
                "entity_edge_generator_prompt_override_used": bool(
                    normalized_entity_edge_generator_prompt_content
                ),
            },
        }

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
