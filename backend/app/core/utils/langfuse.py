import logging
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
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


def create_graphiti_langfuse_tracer() -> Any | None:
    client = get_langfuse_client()
    if client is None:
        return None

    otel_tracer = getattr(client, "_otel_tracer", None)
    if otel_tracer is None:
        logger.debug("Langfuse client has no OTel tracer; Graphiti tracing disabled")
        return None

    try:
        from graphiti_core.tracer import create_tracer
    except ImportError:
        logger.debug("graphiti_core.tracer is unavailable; Graphiti tracing disabled")
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