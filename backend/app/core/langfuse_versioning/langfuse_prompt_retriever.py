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


def _build_labeled_prompt_name(prompt_name: str, label: str | None) -> str | None:
    normalized_label = normalize_label(label)
    if not normalized_label:
        return None

    normalized_prompt_name = _normalize_prompt_name(prompt_name)
    parts = [part for part in normalized_prompt_name.split("/") if part]
    if not parts:
        return None
    if len(parts) == 1:
        return f"{normalized_label}/{parts[0]}"

    category = parts[0]
    if category not in {"prompts", "sub_queries", "fallback_entities"}:
        return None

    file_name = parts[-1]
    return f"{category}/{normalized_label}/{file_name}"


def build_local_path_candidates(name: str, label: str | None) -> list[str]:
    candidates: list[str] = []

    def add_candidate(value: str | None) -> None:
        normalized = _normalize_prompt_name(value or "")
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    normalized_name = _normalize_prompt_name(name)
    if not normalized_name:
        return []

    for label_candidate in build_label_fallback_candidates(label):
        add_candidate(_build_labeled_prompt_name(normalized_name, label_candidate))

    add_candidate(normalized_name)
    return candidates


def _build_prompt_cache_key(
    *,
    prompt_name: str,
    label: str | None,
    version: int | None,
    vars: dict[str, Any],
) -> tuple[Any, ...]:
    vars_signature = tuple(sorted((key, repr(value)) for key, value in vars.items()))
    return (prompt_name, label, version, vars_signature)


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
        version: int | None = None,
        vars: dict[str, Any] | None = None,
        cache_ttl_seconds: int = 300,
    ) -> str:
        prompt_name = name.replace(".md", "").strip("/")
        effective_label = normalize_label(label)
        variables = vars or {}
        cache_key = _build_prompt_cache_key(
            prompt_name=prompt_name,
            label=effective_label,
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
                vars=variables,
            )
        except Exception:
            if stale_value is not None:
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
    def _build_prompt_name_candidates(prompt_name: str, label: str | None) -> list[str]:
        candidates: list[str] = []

        def add_candidate(value: str) -> None:
            normalized = _normalize_prompt_name(value)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        normalized_prompt_name = _normalize_prompt_name(prompt_name)
        if not normalized_prompt_name:
            return []

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
                "prompts",
                "sub_queries",
                "fallback_entities",
            )
            for root in root_candidates:
                root_path = f"{root}/{normalized_prompt_name}"
                add_candidate(root_path)
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
        vars: dict[str, Any],
    ) -> str:
        last_exc: Exception | None = None
        for candidate in self._build_prompt_name_candidates(prompt_name, label):
            try:
                prompt = self.client.get_prompt(
                    candidate,
                    version=version,
                    label=label,
                )
                if hasattr(prompt, "compile"):
                    return prompt.compile(**vars)
                return str(prompt)
            except Exception as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Unable to resolve prompt '{prompt_name}' from provider")
