from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
import logging
import threading
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings as core_settings

logger = logging.getLogger("uvicorn.error")


def _setting(name: str, default: Any) -> Any:
    return getattr(core_settings, name, default)


def _normalize_backend(value: str | None) -> str:
    return (value or "file").strip().lower()


def is_prompt_versioning() -> bool:
    backend = _normalize_backend(_setting("prompt_backend", "file"))
    return backend in {"langfuse", "lanfuse"}


class PromptProvider(ABC):
    @abstractmethod
    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        raise NotImplementedError


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

class FilePromptProvider(PromptProvider):
    def __init__(self, prompt_dir: Path | str) -> None:
        self.prompt_dir = Path(prompt_dir)

    @lru_cache(maxsize=256)
    def _load_raw(self, name: str) -> str:
        path = self.prompt_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path.as_posix()}")
        return path.read_text(encoding="utf-8")

    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        del label, version
        template = self._load_raw(name)
        return self._render_template(template, vars)

    @staticmethod
    def _render_template(template: str, vars: dict[str, Any]) -> str:
        rendered = template
        for key, value in vars.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered


class LangfusePromptProvider(PromptProvider):
    def __init__(self, client: Any | None = None) -> None:
        self._configured = True
        if client is None:
            public_key = os.getenv("LANGFUSE_PUBLIC_KEY", _setting("langfuse_public_key", None))
            secret_key = os.getenv("LANGFUSE_SECRET_KEY", _setting("langfuse_secret_key", None))
            host = os.getenv(
                "LANGFUSE_BASE_URL",
                _setting("langfuse_base_url", _setting("langfuse_host", None)),
            )

            parsed = urlparse(host or "")
            has_valid_host = bool(parsed.scheme in {"http", "https"} and parsed.netloc)
            self._configured = bool(public_key and secret_key and has_valid_host)
            if not self._configured:
                self.client = None
                return

            from langfuse import Langfuse

            client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
        self.client = client

    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        if not self._configured or self.client is None:
            raise RuntimeError("Langfuse prompt provider is not configured")

        prompt_name = name.replace(".md", "").strip("/")
        effective_label = label or _setting("prompt_label", None) or None
        cache_key = _build_prompt_cache_key(
            prompt_name=prompt_name,
            label=effective_label,
            version=version,
            vars=vars,
        )
        now = datetime.now(UTC)
        ttl_seconds = int(_setting("prompt_cache_ttl_seconds", 300))
        if ttl_seconds > 0:
            cached = _LANGFUSE_PROMPT_CACHE.get_fresh(cache_key, now)
            if cached is not None:
                return cached

        stale_value = _LANGFUSE_PROMPT_CACHE.get_stale(cache_key) if ttl_seconds > 0 else None

        try:
            prompt = self.client.get_prompt(
                prompt_name,
                version=version,
                label=effective_label,
            )
            if hasattr(prompt, "compile"):
                rendered = prompt.compile(**vars)
            else:
                rendered = str(prompt)
        except Exception:
            if stale_value is not None:
                logger.warning(
                    "Using stale prompt cache for '%s' after provider failure.",
                    prompt_name,
                )
                return stale_value
            raise

        if ttl_seconds > 0:
            _LANGFUSE_PROMPT_CACHE.set(cache_key, rendered, now, ttl_seconds)
        return rendered


class FallbackPromptProvider(PromptProvider):
    def __init__(self, primary: PromptProvider, fallback: PromptProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        try:
            return self.primary.get(name, label=label, version=version, **vars)
        except Exception as exc:
            logger.warning(
                "Primary prompt provider failed for '%s', fallback to local file: %s",
                name,
                str(exc),
            )
            return self.fallback.get(name, label=label, version=version, **vars)


def _build_prompt_cache_key(
    *,
    prompt_name: str,
    label: str | None,
    version: int | None,
    vars: dict[str, Any],
) -> tuple[Any, ...]:
    vars_signature = tuple(sorted((key, repr(value)) for key, value in vars.items()))
    return (prompt_name, label, version, vars_signature)


def make_prompt_provider(
    *,
    client: Any | None = None,
    prompts_dir: Path | str | None = None,
) -> PromptProvider:
    default_prompt_dir = Path(__file__).resolve().parent / "prompts"
    file_provider = FilePromptProvider(prompts_dir or _setting("prompt_base_dir", default_prompt_dir))

    # Always try provider first, then local files.
    try:
        provider = LangfusePromptProvider(client=client)
    except Exception as exc:
        logger.warning("Prompt provider unavailable, using local files only: %s", str(exc))
        return file_provider

    return FallbackPromptProvider(primary=provider, fallback=file_provider)
