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

    class _Graphiti:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            self.driver = SimpleNamespace()

    fake_driver_module.GraphDriver = _GraphDriver
    fake_graphiti_core.Graphiti = _Graphiti
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


class _GraphFacade:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.ontology_calls: list[dict[str, Any]] = []
        self.add_calls: list[dict[str, Any]] = []
        self.add_batch_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.node = SimpleNamespace(
            get_by_graph_id=lambda graph_id: [SimpleNamespace(uuid="node-1")],
            get=lambda uuid_: SimpleNamespace(uuid=uuid_),
            get_entity_edges=lambda node_uuid: [SimpleNamespace(uuid="edge-1")],
        )
        self.edge = SimpleNamespace(
            get_by_graph_id=lambda graph_id: [SimpleNamespace(uuid="edge-1")],
        )

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.created.append(kwargs)
        return SimpleNamespace(success=True)

    def delete(self, graph_id: str) -> SimpleNamespace:
        self.deleted.append(graph_id)
        return SimpleNamespace(success=True)

    def set_ontology(
        self,
        *,
        graph_ids: list[str],
        entities: dict[str, Any] | None = None,
        edges: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        self.ontology_calls.append(
            {
                "graph_ids": graph_ids,
                "entities": entities,
                "edges": edges,
            }
        )
        return SimpleNamespace(success=True)

    def add(self, **kwargs: Any) -> SimpleNamespace:
        self.add_calls.append(kwargs)
        return SimpleNamespace(uuid="episode-1")

    def add_batch(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.add_batch_calls.append(kwargs)
        return [SimpleNamespace(uuid="episode-1")]

    def search(self, **kwargs: Any) -> SimpleNamespace:
        self.search_calls.append(kwargs)
        return SimpleNamespace(
            nodes=[SimpleNamespace(uuid="node-1")],
            edges=[SimpleNamespace(uuid="edge-1")],
        )


class _LibraryClient:
    def __init__(self) -> None:
        self.graph = _GraphFacade()
        self.client = SimpleNamespace(close=lambda: None)
        self.driver = SimpleNamespace()


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

    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client.client = _LibraryClient()
    client._initialized = True

    client.set_ontology(graph_ids=["graph-1"], entities={"Person": object}, edges=None)
    episode_uuid = client.add_episode(graph_id="graph-1", data="hello world", episode_type="text")

    assert episode_uuid == "episode-1"
    assert client.client.graph.ontology_calls[0]["graph_ids"] == ["graph-1"]
    assert client.client.graph.ontology_calls[0]["entities"] == {"Person": object}
    assert client.client.graph.add_calls[0] == {
        "graph_id": "graph-1",
        "data": "hello world",
        "type": "text",
        "source_description": "graph-1_episodes",
    }


def test_graphiti_oracle_pg_client_forwards_node_and_edge_ops(graphiti_client_module) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient

    class _NodeOps:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

        async def get_by_group_ids(self, *args: Any, **kwargs: Any) -> list[SimpleNamespace]:
            self.calls.append(("get_by_group_ids", args, kwargs))
            return [SimpleNamespace(uuid="node-1")]

        async def get_by_uuid(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
            self.calls.append(("get_by_uuid", args, kwargs))
            return SimpleNamespace(uuid="node-1")

    class _EdgeOps:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

        async def get_by_group_ids(self, *args: Any, **kwargs: Any) -> list[SimpleNamespace]:
            self.calls.append(("get_by_group_ids", args, kwargs))
            return [SimpleNamespace(uuid="edge-1")]

        async def get_by_uuid(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
            self.calls.append(("get_by_uuid", args, kwargs))
            return SimpleNamespace(uuid="edge-1")

        async def get_by_node_uuid(self, *args: Any, **kwargs: Any) -> list[SimpleNamespace]:
            self.calls.append(("get_by_node_uuid", args, kwargs))
            return [SimpleNamespace(uuid="edge-1")]

    node_ops = _NodeOps()
    edge_ops = _EdgeOps()
    driver = SimpleNamespace(entity_node_ops=node_ops, entity_edge_ops=edge_ops)
    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client._driver = driver
    client.client = graphiti_client_module.GraphitiOraclePGClient(
        SimpleNamespace(driver=driver),
        run_async=graphiti_client_module._run_async,
    )

    assert client.client.graph.node.get_by_graph_id(
        "graph-1",
        limit=10,
        uuid_cursor="node-0",
    )[0].uuid == "node-1"
    assert client.client.graph.node.get(uuid_="node-1").uuid == "node-1"
    assert client.client.graph.node.get_entity_edges(node_uuid="node-1")[0].uuid == "edge-1"
    assert client.client.graph.edge.get_by_graph_id(
        "graph-1",
        limit=5,
        uuid_cursor="edge-0",
    )[0].uuid == "edge-1"
    assert client.client.graph.edge.get(uuid_="edge-1").uuid == "edge-1"

    assert node_ops.calls == [
        (
            "get_by_group_ids",
            (driver, ["graph-1"]),
            {"limit": 10, "uuid_cursor": "node-0"},
        ),
        ("get_by_uuid", (driver, "node-1"), {}),
    ]
    assert edge_ops.calls == [
        ("get_by_node_uuid", (driver, "node-1"), {}),
        (
            "get_by_group_ids",
            (driver, ["graph-1"]),
            {"limit": 5, "uuid_cursor": "edge-0"},
        ),
        ("get_by_uuid", (driver, "edge-1"), {}),
    ]


def test_graphiti_delete_graph_clears_cached_ontology(graphiti_client_module) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient
    GraphitiClient._ontology_cache.clear()
    GraphitiClient._set_cached_ontology("graph-1", {"Person": object}, None)

    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client.client = _LibraryClient()
    client._graph_metadata["graph-1"] = {"name": "Graph One"}

    client.delete_graph("graph-1")

    assert client.client.graph.deleted == ["graph-1"]
    assert GraphitiClient._get_cached_ontology("graph-1") == {}


def test_graphiti_add_episode_batch_reads_cached_ontology_kwargs(graphiti_client_module) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient
    GraphitiClient._ontology_cache.clear()

    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client.client = _LibraryClient()
    client._initialized = True

    client.set_ontology(graph_ids=["graph-1"], entities={"Person": object}, edges=None)
    uuids = client.add_episode_batch(
        graph_id="graph-1",
        episodes=[{"data": "chunk-1", "type": "text"}],
    )

    assert uuids == ["episode-1"]
    assert client.client.graph.ontology_calls[0]["graph_ids"] == ["graph-1"]
    assert client.client.graph.add_batch_calls[0] == {
        "graph_id": "graph-1",
        "episodes": [{"data": "chunk-1", "type": "text"}],
    }


def test_graphiti_oracle_initialization_uses_library_factory(
    graphiti_client_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient
    GraphitiClient._ontology_cache.clear()
    created_client = _LibraryClient()
    captured: dict[str, Any] = {}

    captured_connection = None

    def _from_config(connection: Any, **kwargs: Any) -> _LibraryClient:
        nonlocal captured_connection
        captured_connection = connection
        captured.update(kwargs)
        return created_client

    monkeypatch.setattr(
        graphiti_client_module.GraphitiOraclePGClient,
        "from_config",
        staticmethod(_from_config),
    )

    client = GraphitiClient(
        graphiti_db="oracle",
        oracle_connection=graphiti_client_module.GraphitiOraclePGConnection(
            dsn="dsn",
            user="user",
            password="password",
            graph_id="project",
            connect_kwargs={"min": 1, "max": 4, "increment": 1},
            max_coroutines=5,
            log_queries=True,
        ),
        llm_client=object(),
        embedder=object(),
    )
    client.set_ontology(graph_ids=["graph-1"], entities={"Person": object}, edges=None)

    client._ensure_initialized()

    assert client.client is created_client
    assert client._graphiti is created_client.client
    assert not hasattr(client, "_driver")
    assert captured_connection.dsn == "dsn"
    assert captured_connection.user == "user"
    assert captured_connection.password == "password"
    assert captured_connection.graph_id == "project"
    assert captured_connection.connect_kwargs == {"min": 1, "max": 4, "increment": 1}
    assert captured_connection.max_coroutines == 5
    assert captured_connection.log_queries is True
    assert captured["trace_span_prefix"] == "graphiti.oracle"
    assert created_client.graph.ontology_calls[0]["graph_ids"] == ["graph-1"]


def test_graphiti_neo4j_initialization_still_uses_graphiti_constructor(
    graphiti_client_module,
) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient

    client = GraphitiClient(
        graphdb_uri="bolt://localhost",
        graphdb_user="neo4j",
        graphdb_password="password",
        graphiti_db="neo4j",
        llm_client=object(),
        embedder=object(),
    )

    client._ensure_initialized()

    assert client._graphiti.args[:3] == ("bolt://localhost", "neo4j", "password")
    assert client._graphiti.kwargs["trace_span_prefix"] == "graphiti"
    assert client.client.client is client._graphiti


def test_graphiti_search_delegates_to_library_client(graphiti_client_module) -> None:
    GraphitiClient = graphiti_client_module.GraphitiClient
    client = GraphitiClient()
    client._ensure_initialized = lambda: None
    client.client = _LibraryClient()

    result = client.search(graph_id="graph-1", query="alice", limit=7, scope="both")

    assert result.nodes[0].uuid == "node-1"
    assert result.edges[0].uuid == "edge-1"
    assert client.client.graph.search_calls == [
        {
            "graph_id": "graph-1",
            "query": "alice",
            "limit": 7,
            "scope": "both",
            "reranker": "rrf",
        }
    ]
