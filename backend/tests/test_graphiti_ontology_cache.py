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

import asyncio
import importlib
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import Any

import langfuse as langfuse_pkg
import pytest

if not hasattr(langfuse_pkg, "propagate_attributes"):
    @contextmanager
    def _noop_propagate_attributes(**_kwargs: Any):
        yield None

    langfuse_pkg.propagate_attributes = _noop_propagate_attributes


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def set_ontology(
        self,
        graph_ids: list[str],
        entities: dict[str, Any] | None = None,
        edges: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append(
            {
                "graph_ids": graph_ids,
                "entities": entities,
                "edges": edges,
            }
        )


def _install_graphiti_test_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_langfuse = ModuleType("app.core.utils.langfuse")
    fake_langfuse.create_graphiti_langfuse_tracer = lambda **_kwargs: None
    monkeypatch.setitem(sys.modules, "app.core.utils.langfuse", fake_langfuse)

    fake_graphiti_core = ModuleType("graphiti_core")
    fake_driver_pkg = ModuleType("graphiti_core.driver")
    fake_driver_module = ModuleType("graphiti_core.driver.driver")
    fake_nodes_module = ModuleType("graphiti_core.nodes")
    fake_utils_pkg = ModuleType("graphiti_core.utils")
    fake_bulk_module = ModuleType("graphiti_core.utils.bulk_utils")

    class _GraphDriver:
        pass

    class _EpisodeType:
        text = "text"
        message = "message"
        json = "json"

    class _RawEpisode:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    fake_driver_module.GraphDriver = _GraphDriver
    fake_nodes_module.EpisodeType = _EpisodeType
    fake_bulk_module.RawEpisode = _RawEpisode

    monkeypatch.setitem(sys.modules, "graphiti_core", fake_graphiti_core)
    monkeypatch.setitem(sys.modules, "graphiti_core.driver", fake_driver_pkg)
    monkeypatch.setitem(sys.modules, "graphiti_core.driver.driver", fake_driver_module)
    monkeypatch.setitem(sys.modules, "graphiti_core.nodes", fake_nodes_module)
    monkeypatch.setitem(sys.modules, "graphiti_core.utils", fake_utils_pkg)
    monkeypatch.setitem(sys.modules, "graphiti_core.utils.bulk_utils", fake_bulk_module)


@pytest.fixture
def graphiti_client_module(monkeypatch: pytest.MonkeyPatch):
    _install_graphiti_test_stubs(monkeypatch)
    sys.modules.pop("app.core.backend_client_factory.graphiti.graphiti_client", None)
    module = importlib.import_module("app.core.backend_client_factory.graphiti.graphiti_client")
    module._run_async = lambda coro: asyncio.run(coro)
    return module


def test_builder_set_ontology_propagates_empty_state_to_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_graphiti_test_stubs(monkeypatch)
    from app.core.service.graph_builder import GraphBuilderService

    client = _RecordingClient()
    builder = GraphBuilderService(client=client, graph_backend="neo4j")

    builder.set_ontology("graph-1", {"entity_types": [], "edge_types": []})

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["graph_ids"] == ["graph-1"]
    assert call["entities"] is None
    assert call["edges"] is None


def test_graphiti_add_episode_reads_cached_ontology_kwargs(graphiti_client_module) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient
    GraphitiClient._ontology_cache.clear()

    captured: dict[str, Any] = {}

    class _GraphitiStub:
        async def add_episode(self, **kwargs: Any):
            captured.update(kwargs)
            return SimpleNamespace(episode=SimpleNamespace(uuid="episode-1"))

    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client._graphiti = _GraphitiStub()

    client.set_ontology(graph_ids=["graph-1"], entities={"Person": object}, edges=None)
    episode_uuid = client.add_episode(graph_id="graph-1", data="hello world", episode_type="text")

    assert episode_uuid == "episode-1"
    assert captured["group_id"] == "graph-1"
    assert "entity_types" in captured
    assert "Person" in captured["entity_types"]


def test_graphiti_delete_graph_clears_cached_ontology(graphiti_client_module) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient
    GraphitiClient._ontology_cache.clear()
    GraphitiClient._set_cached_ontology("graph-1", {"Person": object}, None)

    class _GraphOps:
        async def clear_data(self, _driver: Any, _group_ids: list[str]) -> None:
            return None

    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client._driver = SimpleNamespace(graph_ops=_GraphOps())
    client._graph_metadata["graph-1"] = {"name": "Graph One"}

    client.delete_graph("graph-1")

    assert GraphitiClient._get_cached_ontology("graph-1") == {}


def test_graphiti_add_episode_batch_reads_cached_ontology_kwargs(graphiti_client_module) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient
    GraphitiClient._ontology_cache.clear()

    captured: dict[str, Any] = {}

    class _GraphitiStub:
        async def add_episode_bulk(self, **kwargs: Any):
            captured.update(kwargs)
            return SimpleNamespace(episodes=[SimpleNamespace(uuid="episode-1")])

    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client._graphiti = _GraphitiStub()

    client.set_ontology(graph_ids=["graph-1"], entities={"Person": object}, edges=None)
    uuids = client.add_episode_batch(
        graph_id="graph-1",
        episodes=[{"data": "chunk-1", "type": "text"}],
    )

    assert uuids == ["episode-1"]
    assert captured["group_id"] == "graph-1"
    assert "entity_types" in captured
    assert "Person" in captured["entity_types"]
