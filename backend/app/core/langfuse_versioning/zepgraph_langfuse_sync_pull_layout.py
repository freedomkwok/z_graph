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

Zep Graph–specific Langfuse pull layout (local paths under output root).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_inference_core.prompts.langfuse_sync_policy import LangfuseSyncPolicy


def normalize_label(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _normalize_prompt_name(value: str | None) -> str:
    return str(value or "").strip().strip("/")


def _normalize_category(value: str) -> str:
    return str(value or "").strip().lower()


def _looks_like_label_segment(value: str, policy: LangfuseSyncPolicy) -> bool:
    return bool(policy.label_pattern.fullmatch(str(value or "").strip().lower()))


def _looks_like_project_scope_segment(value: str, policy: LangfuseSyncPolicy) -> bool:
    return bool(policy.project_scope_pattern.fullmatch(str(value or "").strip().lower()))


def extract_prompt_items(payload: Any, policy: LangfuseSyncPolicy) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in policy.langfuse_list_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def extract_prompt_name_for_pull(item: dict[str, Any], policy: LangfuseSyncPolicy) -> str | None:
    raw_name = item.get("name")
    if not isinstance(raw_name, str):
        return None
    normalized = _normalize_prompt_name(raw_name)
    if not normalized:
        return None
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return None
    category = _normalize_category(parts[0])
    if category not in policy.supported_categories:
        return None
    if category == "ontology_section":
        if len(parts) < 3 or _normalize_category(parts[1]) not in {"prompts", "labels"}:
            return None
    if category == "auto_label_generator":
        if len(parts) < 3 or _normalize_category(parts[1]) not in {"prompts", "labels"}:
            return None
    if ".." in parts:
        return None
    return normalized


def _resolve_file_extension(prompt_name: str) -> str:
    category = _normalize_category(prompt_name.split("/", 1)[0])
    if category == "fallback_entities":
        return ".json"
    return ".md"


def build_pull_target_relative_path(
    prompt_name: str,
    label: str | None,
    policy: LangfuseSyncPolicy,
) -> Path:
    normalized_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_name.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"Invalid prompt name: {prompt_name}")

    category = _normalize_category(parts[0])
    file_name = parts[-1]
    if "." not in file_name:
        file_name = f"{file_name}{_resolve_file_extension(normalized_name)}"

    normalized_label = normalize_label(label)

    if category == "ontology_section":
        section = _normalize_category(parts[1])
        if section == "prompts":
            relative_parts = ["ontology_section", "prompts"]
            trailing_parts = parts[2:-1]
            if trailing_parts and _looks_like_project_scope_segment(trailing_parts[0], policy):
                project_scope = trailing_parts[0]
                remaining_parts = trailing_parts[1:]
                relative_parts.append(project_scope)
                if normalized_label:
                    relative_parts.append(normalized_label)
                    if (
                        remaining_parts
                        and _normalize_category(remaining_parts[0]) == normalized_label
                    ):
                        remaining_parts = remaining_parts[1:]
                elif (
                    remaining_parts
                    and _looks_like_label_segment(remaining_parts[0], policy)
                    and not _looks_like_project_scope_segment(remaining_parts[0], policy)
                ):
                    relative_parts.append(_normalize_category(remaining_parts[0]))
                    remaining_parts = remaining_parts[1:]
                else:
                    relative_parts.append("production")
                relative_parts.extend(remaining_parts)
                relative_parts.append(file_name)
                return Path(*relative_parts)
            if trailing_parts and _looks_like_label_segment(trailing_parts[0], policy):
                if (
                    normalized_label
                    and not _looks_like_project_scope_segment(trailing_parts[0], policy)
                ):
                    trailing_parts = [normalized_label, *trailing_parts[1:]]
                relative_parts.extend(trailing_parts)
            else:
                relative_parts.append(normalized_label or "production")
                relative_parts.extend(trailing_parts)
            relative_parts.append(file_name)
            return Path(*relative_parts)

        if section == "labels":
            relative_parts = ["ontology_section", "labels"]
            trailing_parts = parts[2:-1]
            if not trailing_parts:
                relative_parts.append(normalized_label or "production")
                relative_parts.append(file_name)
                return Path(*relative_parts)

            first_scope = _normalize_category(trailing_parts[0])
            if _looks_like_project_scope_segment(first_scope, policy):
                project_scope = first_scope
                remaining_parts = trailing_parts[1:]
                relative_parts.append(project_scope)
                if normalized_label:
                    relative_parts.append(normalized_label)
                    if (
                        remaining_parts
                        and _normalize_category(remaining_parts[0]) == normalized_label
                    ):
                        remaining_parts = remaining_parts[1:]
                elif (
                    remaining_parts
                    and _looks_like_label_segment(remaining_parts[0], policy)
                    and not _looks_like_project_scope_segment(remaining_parts[0], policy)
                ):
                    relative_parts.append(_normalize_category(remaining_parts[0]))
                    remaining_parts = remaining_parts[1:]
                else:
                    relative_parts.append("production")
                relative_parts.extend(remaining_parts)
            else:
                remaining_parts = trailing_parts[1:]
                if normalized_label:
                    relative_parts.append(normalized_label)
                    if (
                        remaining_parts
                        and _normalize_category(remaining_parts[0]) == normalized_label
                    ):
                        remaining_parts = remaining_parts[1:]
                else:
                    relative_parts.append(first_scope or "production")
                relative_parts.extend(remaining_parts)
            relative_parts.append(file_name)
            return Path(*relative_parts)

        raise ValueError(f"Unsupported ontology_section prompt name: {prompt_name}")

    if category == "auto_label_generator":
        section = _normalize_category(parts[1])
        if section not in {"prompts", "labels"}:
            raise ValueError(f"Unsupported auto_label_generator prompt name: {prompt_name}")
        relative_parts = ["auto_label_generator", section]
        trailing_parts = parts[2:-1]
        if trailing_parts and _looks_like_project_scope_segment(trailing_parts[0], policy):
            project_scope = trailing_parts[0]
            remaining_parts = trailing_parts[1:]
            relative_parts.append(project_scope)
            if normalized_label:
                relative_parts.append(normalized_label)
                if (
                    remaining_parts
                    and _normalize_category(remaining_parts[0]) == normalized_label
                ):
                    remaining_parts = remaining_parts[1:]
            elif (
                remaining_parts
                and _looks_like_label_segment(remaining_parts[0], policy)
                and not _looks_like_project_scope_segment(remaining_parts[0], policy)
            ):
                relative_parts.append(_normalize_category(remaining_parts[0]))
                remaining_parts = remaining_parts[1:]
            else:
                relative_parts.append("production")
            relative_parts.extend(remaining_parts)
            relative_parts.append(file_name)
            return Path(*relative_parts)
        if trailing_parts and _looks_like_label_segment(trailing_parts[0], policy):
            if (
                normalized_label
                and not _looks_like_project_scope_segment(trailing_parts[0], policy)
            ):
                trailing_parts = [normalized_label, *trailing_parts[1:]]
            relative_parts.extend(trailing_parts)
        else:
            relative_parts.append(normalized_label or "production")
            relative_parts.extend(trailing_parts)
        relative_parts.append(file_name)
        return Path(*relative_parts)

    if category == "sub_queries":
        relative_parts = ["sub_queries", "prompts"]
        trailing_parts = parts[1:-1]
        if trailing_parts and _normalize_category(trailing_parts[0]) == "prompts":
            trailing_parts = trailing_parts[1:]
        if trailing_parts and _looks_like_label_segment(trailing_parts[0], policy):
            if (
                normalized_label
                and not _looks_like_project_scope_segment(trailing_parts[0], policy)
            ):
                trailing_parts = [normalized_label, *trailing_parts[1:]]
            relative_parts.extend(trailing_parts)
        else:
            relative_parts.append(normalized_label or "production")
            relative_parts.extend(trailing_parts)
        relative_parts.append(file_name)
        return Path(*relative_parts)

    relative_parts = [_normalize_category(category)]
    trailing_parts = parts[1:-1]

    if normalized_label:
        if trailing_parts and _looks_like_label_segment(trailing_parts[0], policy):
            trailing_parts = trailing_parts[1:]
        relative_parts.append(normalized_label)

    relative_parts.extend(trailing_parts)
    relative_parts.append(file_name)
    return Path(*relative_parts)
