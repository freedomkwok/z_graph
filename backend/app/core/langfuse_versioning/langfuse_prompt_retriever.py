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

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.langfuse_versioning.langfuse_category_label_retriever import (
    PRODUCTION_LABEL,
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


def _is_auto_label_generator_prompt(prompt_name: str) -> bool:
    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    return normalized_prompt_name.startswith("auto_label_generator/prompts/")


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
    if not (
        (parts[0] == "ontology_section" and parts[1] == "labels")
        or (parts[0] == "auto_label_generator" and parts[1] in {"prompts", "labels"})
    ):
        return None

    # Keep compatibility if caller already passes a project-scoped name.
    if len(parts) >= 4 and parts[2] == normalized_project_id:
        return normalized_prompt_name
    if parts[0] == "auto_label_generator" and parts[1] in {"prompts", "labels"}:
        tail_parts = parts[3:] if len(parts) >= 4 else parts[2:]
        if not tail_parts:
            return normalized_prompt_name
        return f"{parts[0]}/{parts[1]}/{normalized_project_id}/{'/'.join(tail_parts)}"
    return f"{parts[0]}/{parts[1]}/{normalized_project_id}/{'/'.join(parts[2:])}"


def _strip_project_scope_from_label_prompt_name(
    prompt_name: str,
    *,
    project_id: str | None = None,
) -> str:
    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_prompt_name.split("/") if part]
    if len(parts) < 4:
        return normalized_prompt_name
    if not (
        (parts[0] == "ontology_section" and parts[1] == "labels")
        or (parts[0] == "auto_label_generator" and parts[1] in {"prompts", "labels"})
    ):
        return normalized_prompt_name

    normalized_project_id = _normalize_project_id(project_id)
    if not normalized_project_id:
        return normalized_prompt_name
    scoped_project_id = parts[2]
    if scoped_project_id != normalized_project_id:
        return normalized_prompt_name
    if parts[0] == "auto_label_generator" and parts[1] in {"prompts", "labels"}:
        tail_parts = parts[3:]
        if not tail_parts:
            return normalized_prompt_name
        return "/".join([parts[0], parts[1], "production", *tail_parts])
    return "/".join([*parts[:2], *parts[3:]])


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
        normalized_project_id = _normalize_project_id(project_id)
        project_prompt_tail = ""
        name_parts = [part for part in normalized_name.split("/") if part]
        if (
            normalized_project_id
            and len(name_parts) >= 4
            and name_parts[0] == "ontology_section"
            and name_parts[1] == "prompts"
            and name_parts[2] == normalized_project_id
        ):
            project_prompt_tail = "/".join(name_parts[3:])
        else:
            base_parts = [part for part in base_prompt_name.split("/") if part]
            project_prompt_tail = "/".join(base_parts[2:])

        if normalized_project_id and project_prompt_tail:
            for label_candidate in build_label_fallback_candidates(label):
                normalized_label_candidate = normalize_label(label_candidate)
                if not normalized_label_candidate:
                    continue
                add_candidate(
                    "ontology_section/prompts/"
                    f"{normalized_project_id}/{normalized_label_candidate}/{project_prompt_tail}"
                )
        for label_candidate in build_label_fallback_candidates(label):
            add_candidate(_build_labeled_prompt_name(base_prompt_name, label_candidate))
        # Compatibility fallbacks.
        add_candidate(base_prompt_name)
        add_candidate(normalized_name)
        return candidates

    if _is_ontology_section_label_prompt(normalized_name):
        label_prompt_tail = normalized_name[len("ontology_section/labels/") :]
        # If incoming path is project-scoped (.../<project_id>/...), strip project scope
        # when falling back to local files because local files only keep global labels.
        tail_parts = [part for part in label_prompt_tail.split("/") if part]
        normalized_project_id = _normalize_project_id(project_id)
        if normalized_project_id and len(tail_parts) >= 2 and tail_parts[0] == normalized_project_id:
            label_prompt_tail = "/".join(tail_parts[1:])

        if normalized_project_id and label_prompt_tail:
            for label_candidate in build_label_fallback_candidates(label):
                normalized_label_candidate = normalize_label(label_candidate)
                if normalized_label_candidate:
                    add_candidate(
                        "ontology_section/labels/"
                        f"{normalized_project_id}/{normalized_label_candidate}/{label_prompt_tail}"
                    )
                project_labeled_candidate = _build_labeled_prompt_name(
                    f"ontology_section/labels/{normalized_project_id}/{label_prompt_tail}",
                    label_candidate,
                )
                add_candidate(project_labeled_candidate)
            add_candidate(f"ontology_section/labels/{normalized_project_id}/{label_prompt_tail}")

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

    if _is_auto_label_generator_prompt(normalized_name):
        normalized_project_id = _normalize_project_id(project_id)
        project_candidate = _build_project_scoped_prompt_name(normalized_name, project_id=project_id)
        if project_candidate:
            add_candidate(project_candidate)
            project_parts = [part for part in project_candidate.split("/") if part]
            if (
                normalized_project_id
                and len(project_parts) >= 4
                and project_parts[2] == normalized_project_id
            ):
                project_prompt_tail = "/".join(project_parts[3:])
                if project_prompt_tail:
                    for label_candidate in build_label_fallback_candidates(label):
                        normalized_label_candidate = normalize_label(label_candidate)
                        if not normalized_label_candidate:
                            continue
                        add_candidate(
                            f"{project_parts[0]}/{project_parts[1]}/"
                            f"{normalized_project_id}/{normalized_label_candidate}/{project_prompt_tail}"
                        )
        add_candidate(
            _strip_project_scope_from_label_prompt_name(
                normalized_name,
                project_id=project_id,
            )
        )
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

    def invalidate(
        self,
        matcher: Callable[[tuple[Any, ...]], bool] | None = None,
    ) -> int:
        with self._lock:
            if matcher is None:
                removed = len(self._entries)
                self._entries.clear()
                return removed

            keys_to_remove = [key for key in self._entries if matcher(key)]
            for key in keys_to_remove:
                self._entries.pop(key, None)
            return len(keys_to_remove)


_LANGFUSE_PROMPT_CACHE = _PromptCache()
_DEFAULT_PROJECT_MISS_TTL_SECONDS = 1800


class _PromptMissCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[Any, ...], datetime] = {}
        self._lock = threading.RLock()

    def has_fresh(self, key: tuple[Any, ...], now: datetime) -> bool:
        with self._lock:
            expires_at = self._entries.get(key)
            if expires_at is None:
                return False
            if now < expires_at:
                return True
            self._entries.pop(key, None)
            return False

    def set(self, key: tuple[Any, ...], now: datetime, ttl_seconds: int) -> None:
        with self._lock:
            self._entries[key] = now + timedelta(seconds=max(ttl_seconds, 1))

    def invalidate(
        self,
        matcher: Callable[[tuple[Any, ...]], bool] | None = None,
    ) -> int:
        with self._lock:
            if matcher is None:
                removed = len(self._entries)
                self._entries.clear()
                return removed
            keys_to_remove = [key for key in self._entries if matcher(key)]
            for key in keys_to_remove:
                self._entries.pop(key, None)
            return len(keys_to_remove)


_LANGFUSE_PROJECT_MISS_CACHE = _PromptMissCache()


def _build_project_probe_key(
    *,
    prompt_name: str,
    label: str | None,
    project_id: str | None,
    version: int | None,
) -> tuple[Any, ...]:
    return (prompt_name, label, project_id, version)


def invalidate_langfuse_prompt_cache(
    *,
    prompt_name: str | None = None,
    label: str | None = None,
    project_id: str | None = None,
) -> int:
    normalized_prompt_name = _normalize_prompt_name(prompt_name or "")
    normalized_label = normalize_label(label)
    normalized_project_id = _normalize_project_id(project_id)

    if not normalized_prompt_name and normalized_label is None and normalized_project_id is None:
        return _LANGFUSE_PROMPT_CACHE.invalidate()

    def _matches(key: tuple[Any, ...]) -> bool:
        key_prompt_name, key_label, key_project_id, _, _ = key
        if normalized_prompt_name and str(key_prompt_name or "") != normalized_prompt_name:
            return False
        if normalized_label is not None and key_label != normalized_label:
            return False
        if normalized_project_id is not None and key_project_id != normalized_project_id:
            return False
        return True

    removed_prompt_cache = _LANGFUSE_PROMPT_CACHE.invalidate(_matches)

    def _matches_project_probe(key: tuple[Any, ...]) -> bool:
        key_prompt_name, key_label, key_project_id, _ = key
        if normalized_prompt_name and str(key_prompt_name or "") != normalized_prompt_name:
            return False
        if normalized_label is not None and key_label != normalized_label:
            return False
        if normalized_project_id is not None and key_project_id != normalized_project_id:
            return False
        return True

    removed_miss_cache = _LANGFUSE_PROJECT_MISS_CACHE.invalidate(_matches_project_probe)
    return removed_prompt_cache + removed_miss_cache


class LangfusePromptRetriever:
    def __init__(self, client: Any, *, logger: logging.Logger | None = None) -> None:
        self.client = client
        self.logger = logger or logging.getLogger("uvicorn.error")

    @staticmethod
    def _format_cache_key(key: tuple[Any, ...]) -> str:
        prompt_name, label, project_id, version, _ = key
        return (
            f"name={prompt_name}, label={label or 'none'}, "
            f"project_id={project_id or 'none'}, version={version or 'latest'}"
        )

    @staticmethod
    def _format_cache_keys_multiline(keys: list[tuple[Any, ...]]) -> str:
        return "\n".join(f"  - {LangfusePromptRetriever._format_cache_key(key)}" for key in keys)

    def get(
        self,
        *,
        name: str,
        label: str | None = None,
        project_id: str | None = None,
        version: int | None = None,
        vars: dict[str, Any] | None = None,
        cache_ttl_seconds: int = 300,
        project_miss_ttl_seconds: int = _DEFAULT_PROJECT_MISS_TTL_SECONDS,
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

        cache_lookup_keys = self._build_cache_lookup_keys(
            prompt_name=prompt_name,
            label=effective_label,
            project_id=effective_project_id,
            version=version,
            vars=variables,
        )
        fallback_cache_lookup_keys = [key for key in cache_lookup_keys if key != cache_key]
        if ttl_seconds > 0:
            cached = _LANGFUSE_PROMPT_CACHE.get_fresh(cache_key, now)
            if cached is not None:
                self.logger.info(
                    "[PromptCacheDebug] fresh primary cache hit -> %s",
                    self._format_cache_key(cache_key),
                )
                return cached

        project_prompt_candidate = _build_project_scoped_prompt_name(
            prompt_name,
            project_id=effective_project_id,
        )
        should_try_project_once = bool(
            effective_project_id
            and project_prompt_candidate
        )
        project_probe_key = _build_project_probe_key(
            prompt_name=prompt_name,
            label=effective_label,
            project_id=effective_project_id,
            version=version,
        )
        has_recent_project_miss = _LANGFUSE_PROJECT_MISS_CACHE.has_fresh(project_probe_key, now)
        if should_try_project_once and has_recent_project_miss:
            self.logger.info(
                "[PromptCacheDebug] skip project scoped probe due recent miss marker -> "
                "name=%s, label=%s, project_id=%s",
                prompt_name,
                effective_label or "none",
                effective_project_id or "none",
            )

        if should_try_project_once and not has_recent_project_miss:
            try:
                rendered_project = self._load_prompt_with_candidates(
                    prompt_name=project_prompt_candidate,
                    version=version,
                    label=effective_label,
                    project_id=None,
                    vars=variables,
                )
                if ttl_seconds > 0:
                    _LANGFUSE_PROMPT_CACHE.set(cache_key, rendered_project, now, ttl_seconds)
                    self.logger.info(
                        "[PromptCacheDebug] set project cache after scoped fetch -> %s",
                        self._format_cache_key(cache_key),
                    )
                return rendered_project
            except Exception as exc:
                if _looks_like_not_found_error(exc):
                    _LANGFUSE_PROJECT_MISS_CACHE.set(
                        project_probe_key,
                        now,
                        int(project_miss_ttl_seconds),
                    )
                    self.logger.info(
                        "[PromptCacheDebug] set project miss marker ttl=%ss -> "
                        "name=%s, label=%s, project_id=%s",
                        int(project_miss_ttl_seconds),
                        prompt_name,
                        effective_label or "none",
                        effective_project_id or "none",
                    )
                else:
                    stale_primary = _LANGFUSE_PROMPT_CACHE.get_stale(cache_key) if ttl_seconds > 0 else None
                    if stale_primary is not None:
                        self.logger.warning(
                            "Using stale project cache for '%s' after scoped lookup failure.",
                            prompt_name,
                        )
                        return stale_primary

        stale_value = None
        stale_key: tuple[Any, ...] | None = None
        if ttl_seconds > 0:
            for key in [cache_key, *fallback_cache_lookup_keys]:
                stale = _LANGFUSE_PROMPT_CACHE.get_stale(key)
                if stale is not None:
                    stale_value = stale
                    stale_key = key
                    break

        if ttl_seconds > 0:
            for key in fallback_cache_lookup_keys:
                cached_fallback = _LANGFUSE_PROMPT_CACHE.get_fresh(key, now)
                if cached_fallback is not None:
                    self.logger.info(
                        "[PromptCacheDebug] fresh fallback cache hit -> %s",
                        self._format_cache_key(key),
                    )
                    return cached_fallback

        try:
            lookup_prompt_name = prompt_name
            lookup_project_id = effective_project_id
            if should_try_project_once:
                lookup_prompt_name = _strip_project_scope_from_label_prompt_name(
                    prompt_name,
                    project_id=effective_project_id,
                )
                lookup_project_id = None
            rendered = self._load_prompt_with_candidates(
                prompt_name=lookup_prompt_name,
                version=version,
                label=effective_label,
                project_id=lookup_project_id,
                vars=variables,
            )
        except Exception as exc:
            # Do not reuse stale prompts for 404/missing cases; allow upper-level provider
            # to fallback to local filesystem prompts.
            if stale_value is not None and not _looks_like_not_found_error(exc):
                self.logger.warning(
                    "Using stale prompt cache for '%s' after provider failure. key=%s",
                    prompt_name,
                    self._format_cache_key(stale_key) if stale_key else "unknown",
                )
                return stale_value
            raise

        if ttl_seconds > 0:
            keys_to_set = cache_lookup_keys if not should_try_project_once else fallback_cache_lookup_keys
            for key in keys_to_set:
                _LANGFUSE_PROMPT_CACHE.set(key, rendered, now, ttl_seconds)
            if keys_to_set:
                self.logger.info(
                    "[PromptCacheDebug] set prompt cache keys:\n%s",
                    self._format_cache_keys_multiline(keys_to_set),
                )
            if not should_try_project_once and cache_key not in keys_to_set:
                _LANGFUSE_PROMPT_CACHE.set(cache_key, rendered, now, ttl_seconds)
                self.logger.info(
                    "[PromptCacheDebug] set prompt cache extra key -> %s",
                    self._format_cache_key(cache_key),
                )
        return rendered

    @staticmethod
    def _build_cache_lookup_keys(
        *,
        prompt_name: str,
        label: str | None,
        project_id: str | None,
        version: int | None,
        vars: dict[str, Any],
    ) -> list[tuple[Any, ...]]:
        keys: list[tuple[Any, ...]] = []

        def add_key(next_prompt_name: str, next_label: str | None, next_project_id: str | None) -> None:
            key = _build_prompt_cache_key(
                prompt_name=next_prompt_name,
                label=next_label,
                project_id=next_project_id,
                version=version,
                vars=vars,
            )
            if key not in keys:
                keys.append(key)

        normalized_prompt_name = _normalize_prompt_name(prompt_name)
        normalized_project_id = _normalize_project_id(project_id)
        add_key(normalized_prompt_name, label, normalized_project_id)

        if normalized_project_id:
            production_prompt_name = _strip_project_scope_from_label_prompt_name(
                normalized_prompt_name,
                project_id=normalized_project_id,
            )
            for fallback_label in build_label_fallback_candidates(
                requested_label=label,
                default_label=PRODUCTION_LABEL,
            ):
                add_key(production_prompt_name, fallback_label, None)

        return keys

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
        # - ontology_section/labels/[<project_id>/]<PROMPT_NAME> (label metadata + optional project scope)
        if _is_ontology_section_base_prompt(normalized_prompt_name):
            base_prompt_name = _normalize_ontology_section_base_prompt_name(normalized_prompt_name)
            # Prefer label-folder candidates first (for consistency with local layout),
            # then fallback to canonical Langfuse naming.
            for label_candidate in build_label_fallback_candidates(label):
                labeled_candidate = _build_labeled_prompt_name(base_prompt_name, label_candidate)
                if labeled_candidate:
                    add_candidate(labeled_candidate)
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
            # Always include unscoped candidate as fallback when project-scoped prompt is absent.
            add_candidate(
                _strip_project_scope_from_label_prompt_name(
                    normalized_prompt_name,
                    project_id=project_id,
                )
            )
            add_candidate(normalized_prompt_name)
            add_candidate(prompt_name)
            return candidates

        if _is_auto_label_generator_prompt(normalized_prompt_name):
            project_candidate = _build_project_scoped_prompt_name(
                normalized_prompt_name,
                project_id=project_id,
            )
            if project_candidate:
                add_candidate(project_candidate)
            add_candidate(
                _strip_project_scope_from_label_prompt_name(
                    normalized_prompt_name,
                    project_id=project_id,
                )
            )
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
            if explicit_candidate_label:
                label_candidates: list[str | None] = [explicit_candidate_label]
            elif _is_ontology_section_label_prompt(candidate) or _is_auto_label_generator_prompt(candidate):
                # For label-driven prompt families, try requested label ->
                # production label -> unlabelled fallback.
                label_candidates = build_label_fallback_candidates(
                    requested_label=label,
                    default_label=PRODUCTION_LABEL,
                )
            else:
                label_candidates = [label]
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
