from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import settings as core_settings
from app.core.langfuse_versioning.langfuse_category_label_retriever import (
    PRODUCTION_LABEL,
    build_label_fallback_candidates,
    normalize_label,
)
from app.core.langfuse_versioning.langfuse_prompt_retriever import (
    LangfusePromptRetriever,
    build_local_path_candidates,
)

logger = logging.getLogger("uvicorn.error")


def _setting(name: str, default: Any) -> Any:
    env_name = str(name or "").strip().upper()
    if env_name:
        env_value = os.getenv(env_name)
        if env_value is not None and str(env_value).strip() != "":
            return env_value
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
        project_id: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        raise NotImplementedError


class FilePromptProvider(PromptProvider):
    def __init__(self, prompt_dir: Path | str) -> None:
        self.prompt_dir = Path(prompt_dir)

    @lru_cache(maxsize=256)
    def _load_raw_by_path(self, relative_path: str) -> str:
        path = self.prompt_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path.as_posix()}")
        return path.read_text(encoding="utf-8")

    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        project_id: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        del version
        last_exc: FileNotFoundError | None = None
        for relative_path in build_local_path_candidates(name, label, project_id=project_id):
            try:
                template = self._load_raw_by_path(relative_path)
                return self._render_template(template, vars)
            except FileNotFoundError as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc
        raise FileNotFoundError(f"Prompt template not found: {name}")

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
                self.retriever = None
                return

            from langfuse import Langfuse

            client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
        self.client = client
        self.retriever = LangfusePromptRetriever(client=self.client, logger=logger)

    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        project_id: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        if not self._configured or self.client is None or self.retriever is None:
            raise RuntimeError("Langfuse prompt provider is not configured")

        cache_ttl_seconds = int(_setting("prompt_cache_ttl_seconds", 300))
        effective_label = normalize_label(label or _setting("prompt_label", None))
        return self.retriever.get(
            name=name,
            label=effective_label,
            project_id=project_id,
            version=version,
            vars=vars,
            cache_ttl_seconds=cache_ttl_seconds,
        )


class FallbackPromptProvider(PromptProvider):
    def __init__(self, primary: PromptProvider, fallback: PromptProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    @staticmethod
    def _is_invalid_prompt_result(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in {"", "none"}
        return False

    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        project_id: str | None = None,
        version: int | None = None,
        **vars: Any,
    ) -> str:
        requested_label = normalize_label(label)
        default_label = normalize_label(_setting("prompt_label", "production"))
        label_candidates = build_label_fallback_candidates(
            requested_label=requested_label,
            default_label=default_label,
        )

        last_exc: Exception | None = None
        for candidate in label_candidates:
            try:
                rendered = self.primary.get(
                    name,
                    label=candidate,
                    project_id=project_id,
                    version=version,
                    **vars,
                )
                if self._is_invalid_prompt_result(rendered):
                    raise RuntimeError(
                        f"Primary prompt provider returned empty content for '{name}'"
                    )
                return str(rendered)
            except Exception as exc:
                last_exc = exc
                continue

        logger.warning(
            "Primary prompt provider failed for '%s' (labels=%s), fallback to local file: %s",
            name,
            ",".join(str(item) for item in label_candidates),
            str(last_exc),
        )
        fallback_last_exc: Exception | None = None
        for fallback_label in label_candidates:
            try:
                rendered = self.fallback.get(
                    name,
                    label=fallback_label,
                    project_id=project_id,
                    version=version,
                    **vars,
                )
                if self._is_invalid_prompt_result(rendered):
                    continue
                return str(rendered)
            except Exception as exc:
                fallback_last_exc = exc
                continue

        if fallback_last_exc is not None:
            raise fallback_last_exc

        return self.fallback.get(
            name,
            label=PRODUCTION_LABEL,
            project_id=project_id,
            version=version,
            **vars,
        )


def make_prompt_provider(
    *,
    client: Any | None = None,
    prompts_dir: Path | str | None = None,
) -> PromptProvider:
    default_prompt_dir = Path(__file__).resolve().parent
    file_provider = FilePromptProvider(prompts_dir or _setting("prompt_base_dir", default_prompt_dir))

    backend = _normalize_backend(_setting("prompt_backend", "file"))
    if backend not in {"langfuse", "lanfuse"}:
        return file_provider

    # Langfuse primary + local file fallback.
    try:
        provider = LangfusePromptProvider(client=client)
    except Exception as exc:
        logger.warning("Prompt provider unavailable, using local files only: %s", str(exc))
        return file_provider

    return FallbackPromptProvider(primary=provider, fallback=file_provider)
