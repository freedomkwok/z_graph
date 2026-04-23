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

import base64
import sys
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import pytest
import langfuse as langfuse_pkg

from app.core.config import Config

if not hasattr(langfuse_pkg, "propagate_attributes"):
    @contextmanager
    def _noop_propagate_attributes(**_kwargs: Any):
        yield None

    langfuse_pkg.propagate_attributes = _noop_propagate_attributes

from app.core.utils import langfuse as langfuse_utils


@pytest.fixture(autouse=True)
def _clear_langfuse_caches() -> None:
    langfuse_utils.get_langfuse_client.cache_clear()
    langfuse_utils._build_graphiti_otel_tracer.cache_clear()
    yield
    langfuse_utils.get_langfuse_client.cache_clear()
    langfuse_utils._build_graphiti_otel_tracer.cache_clear()


def _install_graphiti_tracer_module(create_tracer_func: Any) -> dict[str, ModuleType]:
    fake_tracer_module = ModuleType("graphiti_core.tracer")
    fake_tracer_module.create_tracer = create_tracer_func
    return {"graphiti_core.tracer": fake_tracer_module}


def test_build_graphiti_otel_tracer_uses_langfuse_endpoint_and_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeOTLPSpanExporter:
        def __init__(self, *, endpoint: str, headers: dict[str, str]) -> None:
            captured["endpoint"] = endpoint
            captured["headers"] = headers

    class FakeBatchSpanProcessor:
        def __init__(self, exporter: FakeOTLPSpanExporter) -> None:
            self.exporter = exporter

    class FakeResource:
        @staticmethod
        def create(payload: dict[str, Any]) -> dict[str, Any]:
            return payload

    class FakeTracer:
        @contextmanager
        def start_as_current_span(self, _name: str):
            yield object()

    class FakeTracerProvider:
        def __init__(self, resource: dict[str, Any]) -> None:
            self.resource = resource
            self.processors: list[Any] = []

        def add_span_processor(self, processor: Any) -> None:
            self.processors.append(processor)

        def get_tracer(self, name: str) -> FakeTracer:
            captured["service_name"] = name
            return FakeTracer()

    monkeypatch.setattr(Config, "APPLY_LANGFUSE_TO_GRAPHITI_TRACE", True)
    monkeypatch.setattr(Config, "LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    monkeypatch.setattr(Config, "LANGFUSE_HOST", None)
    monkeypatch.setattr(Config, "LANGFUSE_OTEL_ENDPOINT", "")
    monkeypatch.setattr(Config, "LANGFUSE_OTEL_AUTH", "")
    monkeypatch.setattr(Config, "LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr(Config, "LANGFUSE_SECRET_KEY", "sk-test")

    fake_modules = {
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": ModuleType(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter"
        ),
        "opentelemetry.sdk.resources": ModuleType("opentelemetry.sdk.resources"),
        "opentelemetry.sdk.trace": ModuleType("opentelemetry.sdk.trace"),
        "opentelemetry.sdk.trace.export": ModuleType("opentelemetry.sdk.trace.export"),
    }
    fake_modules["opentelemetry.exporter.otlp.proto.http.trace_exporter"].OTLPSpanExporter = (
        FakeOTLPSpanExporter
    )
    fake_modules["opentelemetry.sdk.resources"].Resource = FakeResource
    fake_modules["opentelemetry.sdk.trace"].TracerProvider = FakeTracerProvider
    fake_modules["opentelemetry.sdk.trace.export"].BatchSpanProcessor = FakeBatchSpanProcessor

    with pytest.MonkeyPatch.context() as module_patch:
        module_patch.setitem(sys.modules, "opentelemetry.exporter.otlp.proto.http.trace_exporter", fake_modules["opentelemetry.exporter.otlp.proto.http.trace_exporter"])
        module_patch.setitem(sys.modules, "opentelemetry.sdk.resources", fake_modules["opentelemetry.sdk.resources"])
        module_patch.setitem(sys.modules, "opentelemetry.sdk.trace", fake_modules["opentelemetry.sdk.trace"])
        module_patch.setitem(sys.modules, "opentelemetry.sdk.trace.export", fake_modules["opentelemetry.sdk.trace.export"])
        tracer = langfuse_utils._build_graphiti_otel_tracer()

    assert tracer is not None
    assert captured["endpoint"] == "https://cloud.langfuse.com/api/public/otel"
    expected = base64.b64encode(b"pk-test:sk-test").decode()
    assert captured["headers"]["Authorization"] == f"Basic {expected}"
    assert captured["service_name"] == "graphiti"


def test_create_graphiti_tracer_prefers_dedicated_otel_tracer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DedicatedTracer:
        @contextmanager
        def start_as_current_span(self, _name: str):
            yield object()

    dedicated_tracer = DedicatedTracer()
    create_calls: dict[str, Any] = {}

    def fake_create_tracer(*, otel_tracer: Any, span_prefix: str) -> dict[str, Any]:
        create_calls["otel_tracer"] = otel_tracer
        create_calls["span_prefix"] = span_prefix
        return {"wrapped": True, "otel_tracer": otel_tracer, "span_prefix": span_prefix}

    class UnexpectedClient:
        pass

    monkeypatch.setattr(Config, "APPLY_LANGFUSE_TO_GRAPHITI_TRACE", True)
    monkeypatch.setattr(langfuse_utils, "_build_graphiti_otel_tracer", lambda: dedicated_tracer)
    monkeypatch.setattr(langfuse_utils, "get_langfuse_client", lambda: UnexpectedClient())

    with pytest.MonkeyPatch.context() as module_patch:
        module_patch.setitem(
            sys.modules,
            "graphiti_core.tracer",
            _install_graphiti_tracer_module(fake_create_tracer)["graphiti_core.tracer"],
        )
        result = langfuse_utils.create_graphiti_langfuse_tracer()

    assert result["wrapped"] is True
    assert create_calls["otel_tracer"] is dedicated_tracer
    assert create_calls["span_prefix"] == "graphiti.llm"


def test_create_graphiti_tracer_falls_back_to_langfuse_observation_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeObservation:
        def update(self, **_kwargs: Any) -> None:
            return None

    class FakeClient:
        @contextmanager
        def start_as_current_observation(self, **_kwargs: Any):
            yield FakeObservation()

    def fake_create_tracer(*, otel_tracer: Any, span_prefix: str) -> Any:
        assert span_prefix == "graphiti.llm"
        return otel_tracer

    monkeypatch.setattr(Config, "APPLY_LANGFUSE_TO_GRAPHITI_TRACE", True)
    monkeypatch.setattr(langfuse_utils, "_build_graphiti_otel_tracer", lambda: None)
    monkeypatch.setattr(langfuse_utils, "get_langfuse_client", lambda: FakeClient())

    with pytest.MonkeyPatch.context() as module_patch:
        module_patch.setitem(
            sys.modules,
            "graphiti_core.tracer",
            _install_graphiti_tracer_module(fake_create_tracer)["graphiti_core.tracer"],
        )
        bridge = langfuse_utils.create_graphiti_langfuse_tracer()

    assert isinstance(bridge, langfuse_utils._LangfuseTracerSpanBridge)
    with bridge.start_as_current_span("span-name") as span:
        span.set_attributes({"k": "v"})


def test_create_graphiti_tracer_returns_none_when_request_disables_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_create_tracer(*, otel_tracer: Any, span_prefix: str) -> dict[str, Any]:
        return {"otel_tracer": otel_tracer, "span_prefix": span_prefix}

    monkeypatch.setattr(Config, "APPLY_LANGFUSE_TO_GRAPHITI_TRACE", True)
    monkeypatch.setattr(langfuse_utils, "_build_graphiti_otel_tracer", lambda: object())

    with pytest.MonkeyPatch.context() as module_patch:
        module_patch.setitem(
            sys.modules,
            "graphiti_core.tracer",
            _install_graphiti_tracer_module(fake_create_tracer)["graphiti_core.tracer"],
        )
        result = langfuse_utils.create_graphiti_langfuse_tracer(enable_for_request=False)

    assert result is None
