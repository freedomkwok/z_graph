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

import base64
import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langfuse import Langfuse, propagate_attributes

from app.core.config import Config

logger = logging.getLogger("uvicorn.error")


@dataclass
class LangfuseEntity:
    trace_id: str | None = None
    observation_id: str | None = None

@lru_cache(maxsize=1)
def get_langfuse_client() -> Langfuse | None:
    """
    Lazily create and cache a single Langfuse client from project config.
    Returns None when Langfuse keys are not configured.
    """
    if not Config.LANGFUSE_PUBLIC_KEY or not Config.LANGFUSE_SECRET_KEY:
        return None

    try:
        return Langfuse(
            public_key=Config.LANGFUSE_PUBLIC_KEY,
            secret_key=Config.LANGFUSE_SECRET_KEY,
            host=Config.LANGFUSE_HOST,
        )
    except Exception:
        logger.exception("Failed to initialize Langfuse client")
        return None

def session_context(session_id: str | None):
    return propagate_attributes(session_id=session_id) if session_id is not None else nullcontext()


@lru_cache(maxsize=1)
def _build_graphiti_otel_tracer() -> Any | None:
    """Build a dedicated OTel tracer for Graphiti -> Langfuse export."""
    if not Config.APPLY_LANGFUSE_TO_GRAPHITI_TRACE:
        return None

    endpoint = str(Config.LANGFUSE_OTEL_ENDPOINT or "").strip()
    if not endpoint:
        base = str(Config.LANGFUSE_BASE_URL or Config.LANGFUSE_HOST or "").strip().rstrip("/")
        if not base:
            logger.warning(
                "Graphiti OTel tracing enabled, but LANGFUSE_BASE_URL/LANGFUSE_HOST is missing"
            )
            return None
        endpoint = f"{base}/api/public/otel"

    auth_header = str(Config.LANGFUSE_OTEL_AUTH or "").strip()
    if not auth_header:
        if not Config.LANGFUSE_PUBLIC_KEY or not Config.LANGFUSE_SECRET_KEY:
            logger.warning(
                "Graphiti OTel tracing enabled, but Langfuse public/secret keys are missing"
            )
            return None
        # Fallback auth header format expected by Langfuse OTLP endpoint:
        # Authorization: Basic base64(public_key:secret_key)
        langfuse_auth = base64.b64encode(
            f"{Config.LANGFUSE_PUBLIC_KEY}:{Config.LANGFUSE_SECRET_KEY}".encode()
        ).decode()
        auth_header = f"Basic {langfuse_auth}"

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "Graphiti OTel tracing requires opentelemetry-sdk and "
            "opentelemetry-exporter-otlp-proto-http"
        )
        return None

    try:
        provider = TracerProvider(resource=Resource.create({"service.name": "graphiti"}))
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=endpoint,
                    headers={"Authorization": auth_header},
                )
            )
        )
        logger.info("Graphiti OTel tracer initialized for Langfuse endpoint")
        return provider.get_tracer("graphiti")
    except Exception:
        logger.exception("Failed to initialize Graphiti OTel tracer for Langfuse")
        return None


def _is_graphiti_compatible_otel_tracer(candidate: Any) -> bool:
    """Graphiti tracer wrapper expects OTel tracers with start_as_current_span."""
    return callable(getattr(candidate, "start_as_current_span", None))


def _resolve_graphiti_otel_tracer(candidate: Any) -> Any | None:
    """Best-effort coercion for tracer/provider wrappers returned by SDKs."""
    if candidate is None:
        return None
    if _is_graphiti_compatible_otel_tracer(candidate):
        return candidate

    # Some SDKs expose a tracer provider-like object.
    get_tracer = getattr(candidate, "get_tracer", None)
    if callable(get_tracer):
        try:
            resolved = get_tracer("graphiti")
            if _is_graphiti_compatible_otel_tracer(resolved):
                return resolved
        except Exception:
            logger.debug("Failed to resolve tracer from provider wrapper", exc_info=True)

    # Some SDK wrappers nest the actual tracer object.
    for attr_name in ("tracer", "_tracer", "otel_tracer", "_otel_tracer"):
        nested = getattr(candidate, attr_name, None)
        if _is_graphiti_compatible_otel_tracer(nested):
            return nested

    return None


class _LangfuseObservationSpanAdapter:
    """Minimal span-like adapter expected by graphiti_core OpenTelemetry wrapper."""

    def __init__(self, observation: Any) -> None:
        self._observation = observation
        self._metadata: dict[str, Any] = {}

    def _safe_update(self, **kwargs: Any) -> None:
        try:
            updater = getattr(self._observation, "update", None)
            if callable(updater):
                updater(**kwargs)
        except Exception:
            logger.debug("Langfuse observation update failed inside tracer adapter", exc_info=True)

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        if not isinstance(attributes, dict):
            return
        self._metadata.update({str(k): v for k, v in attributes.items()})
        self._safe_update(metadata=self._metadata)

    def set_status(self, status: Any, description: str | None = None) -> None:
        status_payload = {
            "graphiti_status": str(status),
        }
        if description:
            status_payload["graphiti_status_description"] = description
        self._metadata.update(status_payload)
        self._safe_update(metadata=self._metadata)

    def record_exception(self, exception: Exception) -> None:
        self._safe_update(output={"error": str(exception)})


class _LangfuseTracerSpanBridge:
    """Expose start_as_current_span() by delegating to Langfuse observations."""

    def __init__(self, client: Langfuse) -> None:
        self._client = client

    @contextmanager
    def start_as_current_span(self, name: str):
        with self._client.start_as_current_observation(name=name, as_type="span") as observation:
            yield _LangfuseObservationSpanAdapter(observation)


def create_graphiti_langfuse_tracer(enable_for_request: bool | None = None) -> Any | None:
    try:
        from graphiti_core.tracer import create_tracer
    except ImportError:
        logger.debug("graphiti_core.tracer is unavailable; Graphiti tracing disabled")
        return None

    # Request-level gate: defaults to global config, can be overridden by Step B toggle.
    tracing_enabled = (
        Config.APPLY_LANGFUSE_TO_GRAPHITI_TRACE
        if enable_for_request is None
        else bool(enable_for_request)
    )
    if not tracing_enabled:
        logger.debug("Graphiti tracing disabled by request/global setting")
        return None

    dedicated_otel_tracer = _resolve_graphiti_otel_tracer(_build_graphiti_otel_tracer())
    if dedicated_otel_tracer is not None:
        try:
            return create_tracer(otel_tracer=dedicated_otel_tracer, span_prefix="graphiti.llm")
        except Exception:
            logger.debug("Failed to create Graphiti tracer from dedicated OTel tracer", exc_info=True)

    client = get_langfuse_client()
    if client is None:
        return None

    raw_otel_tracer = getattr(client, "_otel_tracer", None)
    if raw_otel_tracer is None:
        raw_otel_tracer = getattr(client, "otel_tracer", None)

    otel_tracer = _resolve_graphiti_otel_tracer(raw_otel_tracer)
    if otel_tracer is None and callable(getattr(client, "start_as_current_observation", None)):
        otel_tracer = _LangfuseTracerSpanBridge(client)
        logger.info("Using Langfuse observation bridge tracer for Graphiti")
    if otel_tracer is None:
        logger.warning(
            "Langfuse tracer is unavailable/incompatible for Graphiti "
            "(missing start_as_current_span). "
            "Set APPLY_LANGFUSE_TO_GRAPHITI_TRACE=true to use dedicated OTLP tracer."
        )
        return None

    try:
        return create_tracer(otel_tracer=otel_tracer, span_prefix="graphiti.llm")
    except Exception:
        logger.debug("Failed to create Graphiti OpenTelemetry tracer from Langfuse", exc_info=True)
        return None


async def run_with_langfuse_trace(
    *,
    langfuse_type: str,
    trace_name: str,
    trace_input: Any,
    runner: Callable[[], Awaitable[Any]],
    langfuse: Langfuse | None = None,
    on_success: Callable[[Any, Any], None] | None = None,
    metadata: dict[str, Any] | None = None,
    model_name: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    flush_on_exit: bool = False,
) -> tuple[Any, LangfuseEntity]:
    """
    Execute an async operation inside a Langfuse observation.
    If no client is configured, runs normally without tracing.
    """
    client = langfuse or get_langfuse_client()
    if client is None:
        return await runner()

    trace_kwargs: dict[str, Any] = {
        "name": trace_name,
        "as_type": langfuse_type,
        "input" : trace_input
    }
    if model_name is not None:
        trace_kwargs["model"] = model_name
    if metadata is not None:
        trace_kwargs["metadata"] = metadata
    if parent_span_id is not None:
        trace_kwargs["trace_context"] = {"trace_id": trace_id, "parent_span_id": parent_span_id}
    elif trace_id is not None:
        trace_kwargs["trace_context"] = {"trace_id": trace_id}

    with session_context(session_id) as session:
        with client.start_as_current_observation(**trace_kwargs) as observation:
            lanfuse_entity = LangfuseEntity(
                trace_id=observation.get_current_trace_id(),
                observation_id=observation.get_current_observation_id(),
            )
            try:
                result = await runner()
                if on_success is not None:
                    on_success(result, observation)
                return (result, lanfuse_entity)
            except Exception as exc:
                if hasattr(observation, "update"):
                    observation.update(output={"error": str(exc)})
                raise
            finally:
                if flush_on_exit:
                    client.flush()