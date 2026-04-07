from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.langfuse_versioning.langfuse_category_label_retriever import (
    build_label_fallback_candidates,
    normalize_label,
)


def _normalize_prompt_name(value: str) -> str:
    return str(value or "").strip().strip("/")


def _normalize_project_id(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _is_ontology_section_label_prompt(prompt_name: str) -> bool:
    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    return normalized_prompt_name.startswith("ontology_section/labels/")


def _is_ontology_section_base_prompt(prompt_name: str) -> bool:
    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    return normalized_prompt_name.startswith("ontology_section/prompts/")


def _normalize_ontology_section_base_prompt_name(prompt_name: str) -> str:
    """Normalize ontology base prompt names to: ontology_section/prompts/<PROMPT_NAME>."""
    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_prompt_name.split("/") if part]
    if len(parts) >= 4 and parts[0] == "ontology_section" and parts[1] == "prompts":
        return f"ontology_section/prompts/{'/'.join(parts[3:])}"
    return normalized_prompt_name


def _extract_ontology_section_prompt_label(prompt_name: str) -> str | None:
    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_prompt_name.split("/") if part]
    if len(parts) < 4:
        return None
    if not (parts[0] == "ontology_section" and parts[1] == "prompts"):
        return None
    return normalize_label(parts[2])


def _build_project_scoped_prompt_name(prompt_name: str, project_id: str | None) -> str | None:
    normalized_project_id = _normalize_project_id(project_id)
    if not normalized_project_id:
        return None

    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_prompt_name.split("/") if part]
    if len(parts) < 3:
        return None
    if not (parts[0] == "ontology_section" and parts[1] == "labels"):
        return None

    # Keep compatibility if caller already passes a project-scoped name.
    if len(parts) >= 4 and parts[-1] == normalized_project_id:
        return normalized_prompt_name
    return f"ontology_section/labels/{'/'.join(parts[2:])}/{normalized_project_id}"


def _build_labeled_prompt_name(prompt_name: str, label: str | None) -> str | None:
    normalized_label = normalize_label(label)
    if not normalized_label:
        return None

    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_prompt_name.split("/") if part]
    if not parts:
        return None

    # Local ontology section files keep labels as a physical folder level.
    # Example:
    #   ontology_section/labels/ENTITY_EXAMPLES_IN_SYSTEM_PROMPT.md
    # -> ontology_section/labels/production/ENTITY_EXAMPLES_IN_SYSTEM_PROMPT.md
    if len(parts) >= 3 and parts[0] == "ontology_section" and parts[1] == "labels":
        tail = "/".join(parts[2:])
        return f"ontology_section/labels/{normalized_label}/{tail}"

    # Local fallback files for base ontology prompts are label-folder based.
    # Example:
    #   ontology_section/prompts/ONTOLOGY_SYSTEM_PROMPT
    # -> ontology_section/prompts/production/ONTOLOGY_SYSTEM_PROMPT
    if len(parts) >= 3 and parts[0] == "ontology_section" and parts[1] == "prompts":
        tail_parts = parts[2:]
        if len(parts) >= 4:
            tail_parts = [normalized_label, *tail_parts[1:]]
        else:
            tail_parts = [normalized_label, *tail_parts]
        return f"ontology_section/prompts/{'/'.join(tail_parts)}"

    if len(parts) == 1:
        return f"{normalized_label}/{parts[0]}"

    category = parts[0]
    if category not in {"sub_queries", "fallback_entities"}:
        return None

    file_name = parts[-1]
    return f"{category}/{normalized_label}/{file_name}"


def build_local_path_candidates(
    name: str,
    label: str | None,
    *,
    project_id: str | None = None,
) -> list[str]:
    candidates: list[str] = []

    def add_candidate(value: str | None) -> None:
        normalized = _normalize_prompt_name(value or "")
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    normalized_name = _normalize_prompt_name(name)
    if not normalized_name:
        return []

    # Base ontology prompts are label-folder based:
    # ontology_section/prompts/<label>/<PROMPT_NAME>
    if _is_ontology_section_base_prompt(normalized_name):
        base_prompt_name = _normalize_ontology_section_base_prompt_name(normalized_name)
        for label_candidate in build_label_fallback_candidates(label):
            add_candidate(_build_labeled_prompt_name(base_prompt_name, label_candidate))
        # Compatibility fallbacks.
        add_candidate(base_prompt_name)
        add_candidate(normalized_name)
        return candidates

    if _is_ontology_section_label_prompt(normalized_name):
        label_prompt_tail = normalized_name[len("ontology_section/labels/") :]
        # If incoming path is project-scoped (.../<project_id>), strip project scope
        # when falling back to local files because local files only keep global labels.
        tail_parts = [part for part in label_prompt_tail.split("/") if part]
        normalized_project_id = _normalize_project_id(project_id)
        if normalized_project_id and len(tail_parts) >= 2 and tail_parts[-1] == normalized_project_id:
            label_prompt_tail = "/".join(tail_parts[:-1])

        for label_candidate in build_label_fallback_candidates(label):
            labeled_candidate = _build_labeled_prompt_name(
                f"ontology_section/labels/{label_prompt_tail}",
                label_candidate,
            )
            add_candidate(labeled_candidate)

        # Final compatibility fallbacks.
        add_candidate(f"ontology_section/labels/{label_prompt_tail}")
        add_candidate(normalized_name)
        return candidates

    for label_candidate in build_label_fallback_candidates(label):
        add_candidate(_build_labeled_prompt_name(normalized_name, label_candidate))

    add_candidate(normalized_name)
    return candidates


def _build_prompt_cache_key(
    *,
    prompt_name: str,
    label: str | None,
    project_id: str | None,
    version: int | None,
    vars: dict[str, Any],
) -> tuple[Any, ...]:
    vars_signature = tuple(sorted((key, repr(value)) for key, value in vars.items()))
    return (prompt_name, label, project_id, version, vars_signature)


def _looks_like_not_found_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "not found" in message or "404" in message


class _PromptCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[Any, ...], tuple[str, datetime]] = {}
        self._lock = threading.RLock()

    def get_fresh(self, key: tuple[Any, ...], now: datetime) -> str | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if now < expires_at:
                return value
            return None

    def get_stale(self, key: tuple[Any, ...]) -> str | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            return entry[0]

    def set(self, key: tuple[Any, ...], value: str, now: datetime, ttl_seconds: int) -> None:
        with self._lock:
            self._entries[key] = (value, now + timedelta(seconds=max(ttl_seconds, 1)))


_LANGFUSE_PROMPT_CACHE = _PromptCache()


class LangfusePromptRetriever:
    def __init__(self, client: Any, *, logger: logging.Logger | None = None) -> None:
        self.client = client
        self.logger = logger or logging.getLogger("uvicorn.error")

    def get(
        self,
        *,
        name: str,
        label: str | None = None,
        project_id: str | None = None,
        version: int | None = None,
        vars: dict[str, Any] | None = None,
        cache_ttl_seconds: int = 300,
    ) -> str:
        prompt_name = name.replace(".md", "").strip("/")
        effective_label = normalize_label(label)
        effective_project_id = _normalize_project_id(project_id)
        variables = vars or {}
        cache_key = _build_prompt_cache_key(
            prompt_name=prompt_name,
            label=effective_label,
            project_id=effective_project_id,
            version=version,
            vars=variables,
        )
        now = datetime.now(timezone.utc)
        ttl_seconds = int(cache_ttl_seconds)
        if ttl_seconds > 0:
            cached = _LANGFUSE_PROMPT_CACHE.get_fresh(cache_key, now)
            if cached is not None:
                return cached

        stale_value = _LANGFUSE_PROMPT_CACHE.get_stale(cache_key) if ttl_seconds > 0 else None

        try:
            rendered = self._load_prompt_with_candidates(
                prompt_name=prompt_name,
                version=version,
                label=effective_label,
                project_id=effective_project_id,
                vars=variables,
            )
        except Exception as exc:
            # Do not reuse stale prompts for 404/missing cases; allow upper-level provider
            # to fallback to local filesystem prompts.
            if stale_value is not None and not _looks_like_not_found_error(exc):
                self.logger.warning(
                    "Using stale prompt cache for '%s' after provider failure.",
                    prompt_name,
                )
                return stale_value
            raise

        if ttl_seconds > 0:
            _LANGFUSE_PROMPT_CACHE.set(cache_key, rendered, now, ttl_seconds)
        return rendered

    @staticmethod
    def _build_prompt_name_candidates(
        prompt_name: str,
        label: str | None,
        *,
        project_id: str | None = None,
    ) -> list[str]:
        candidates: list[str] = []

        def add_candidate(value: str) -> None:
            normalized = _normalize_prompt_name(value)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        normalized_prompt_name = _normalize_prompt_name(prompt_name)
        if not normalized_prompt_name:
            return []

        # Ontology-section layout:
        # - ontology_section/prompts/<PROMPT_NAME> (label via Langfuse label metadata)
        # - ontology_section/labels/<PROMPT_NAME>[/<project_id>] (label metadata + optional project scope)
        if _is_ontology_section_base_prompt(normalized_prompt_name):
            base_prompt_name = _normalize_ontology_section_base_prompt_name(normalized_prompt_name)
            # Canonical naming only: ontology_section/prompts/<PROMPT_NAME> + label metadata.
            add_candidate(base_prompt_name)
            add_candidate(normalized_prompt_name)
            add_candidate(prompt_name)
            return candidates

        if _is_ontology_section_label_prompt(normalized_prompt_name):
            project_candidate = _build_project_scoped_prompt_name(
                normalized_prompt_name,
                project_id=project_id,
            )
            if project_candidate:
                add_candidate(project_candidate)
            add_candidate(normalized_prompt_name)
            add_candidate(prompt_name)
            return candidates

        if "/" in normalized_prompt_name:
            for label_candidate in build_label_fallback_candidates(label):
                labeled_candidate = _build_labeled_prompt_name(normalized_prompt_name, label_candidate)
                if labeled_candidate:
                    add_candidate(labeled_candidate)

        add_candidate(normalized_prompt_name)
        add_candidate(prompt_name)

        # Support folder-structured names synced from langfuse_versioning.
        if "/" not in normalized_prompt_name:
            root_candidates = (
                "sub_queries",
                "fallback_entities",
                "ontology_section/prompts",
                "ontology_section/labels",
            )
            for root in root_candidates:
                root_path = f"{root}/{normalized_prompt_name}"
                add_candidate(root_path)
                if root == "ontology_section/labels":
                    project_candidate = _build_project_scoped_prompt_name(
                        root_path,
                        project_id=project_id,
                    )
                    if project_candidate:
                        add_candidate(project_candidate)
                    continue

                for label_candidate in build_label_fallback_candidates(label):
                    labeled_root_path = _build_labeled_prompt_name(root_path, label_candidate)
                    if labeled_root_path:
                        add_candidate(labeled_root_path)

        return candidates

    def _load_prompt_with_candidates(
        self,
        *,
        prompt_name: str,
        version: int | None,
        label: str | None,
        project_id: str | None,
        vars: dict[str, Any],
    ) -> str:
        last_exc: Exception | None = None
        for candidate in self._build_prompt_name_candidates(
            prompt_name,
            label,
            project_id=project_id,
        ):
            explicit_candidate_label = _extract_ontology_section_prompt_label(candidate)
            label_candidates: list[str | None] = [explicit_candidate_label or label]
            if None not in label_candidates:
                label_candidates.append(None)

            for candidate_label in label_candidates:
                try:
                    prompt = self.client.get_prompt(
                        candidate,
                        version=version,
                        label=candidate_label,
                    )
                    if prompt is None:
                        raise RuntimeError(f"Prompt '{candidate}' returned no content")
                    if hasattr(prompt, "compile"):
                        rendered = prompt.compile(**vars)
                        if rendered is None:
                            raise RuntimeError(f"Prompt '{candidate}' compiled to empty content")
                        return str(rendered)
                    return str(prompt)
                except Exception as exc:
                    last_exc = exc
                    continue

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Unable to resolve prompt '{prompt_name}' from provider")
