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

import asyncio
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from graphiti_client import (  # pyright: ignore[reportMissingImports]
    GraphitiOraclePGClient,
    GraphitiOraclePGConnection,
)

from app.core.backend_client_factory.schema import (
    EpisodeStatus,
    GraphEdge,
    GraphNode,
    SearchResult,
    ZepClientAdapter,
)
from app.core.config import Config
from app.core.utils.langfuse import create_graphiti_langfuse_tracer

logger = logging.getLogger('z_graph.graphiti_client')

_async_loop: Optional[asyncio.AbstractEventLoop] = None
_async_thread: Optional[threading.Thread] = None
_init_lock = threading.Lock()

def _start_async_loop():
    global _async_loop
    _async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_async_loop)
    logger.info("Graphiti async loop has been started")
    _async_loop.run_forever()


def _ensure_async_loop():
    global _async_thread
    with _init_lock:
        if _async_thread is None or not _async_thread.is_alive():
            _async_thread = threading.Thread(
                target=_start_async_loop,
                daemon=True,
                name="graphiti-async-loop"
            )
            _async_thread.start()

    # Wait for loop to become available and running.
    import time
    timeout_seconds = 5.0
    deadline = time.time() + timeout_seconds
    while True:
        loop = _async_loop
        if loop is not None and not loop.is_closed() and loop.is_running():
            return loop
        if time.time() >= deadline:
            raise RuntimeError("Graphiti async loop failed to initialize")
        time.sleep(0.01)


def _run_async(coro):
    loop = _ensure_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=900)  # Timeout is 5 minutes

class EmbedderClientWrapper:
    def __init__(self, embedder: Any, max_batch_size: int = 10):
        self._embedder = embedder
        self.max_batch_size = max_batch_size
        if hasattr(embedder, 'config'):
            self.config = embedder.config

    async def create(self, input_data) -> list[float]:
        return await self._embedder.create(input_data)

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        if len(input_data_list) <= self.max_batch_size:
            return await self._embedder.create_batch(input_data_list)

        results = []
        for i in range(0, len(input_data_list), self.max_batch_size):
            chunk = input_data_list[i : i + self.max_batch_size]
            chunk_results = await self._embedder.create_batch(chunk)
            results.extend(chunk_results)
        return results


def _create_dashscope_embedder_wrapper(base_embedder: Any, max_batch_size: int = 10) -> Any:
    try:
        from graphiti_core.embedder.client import EmbedderClient

        class _DynamicEmbedderClient(EmbedderClient):
            def __init__(self, embedder: Any, batch_size: int):
                self._embedder = embedder
                self.max_batch_size = batch_size
                if hasattr(embedder, 'config'):
                    self.config = embedder.config

            async def create(self, input_data) -> list[float]:
                return await self._embedder.create(input_data)

            async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
                if len(input_data_list) <= self.max_batch_size:
                    return await self._embedder.create_batch(input_data_list)

                results = []
                for i in range(0, len(input_data_list), self.max_batch_size):
                    chunk = input_data_list[i : i + self.max_batch_size]
                    chunk_results = await self._embedder.create_batch(chunk)
                    results.extend(chunk_results)
                return results

        return _DynamicEmbedderClient(base_embedder, max_batch_size)

    except ImportError:
        return EmbedderClientWrapper(base_embedder, max_batch_size)


class GraphitiClient(ZepClientAdapter):
    _ONTOLOGY_CACHE_MAX_SIZE = 200
    _ontology_cache_lock = threading.Lock()
    _ontology_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def __init__(
        self,
        graphdb_uri: str | None = None,
        graphdb_user: str | None = None,
        graphdb_password: str | None = None,
        llm_client: Optional[Any] = None,
        embedder: Optional[Any] = None,
        embedding_model: str | None = None,
        enable_otel_tracing: bool | None = None,
        graphiti_db: str | None = None,
        oracle_connection: GraphitiOraclePGConnection | None = None,
    ):
        self.graphdb_uri = graphdb_uri
        self.graphdb_user = graphdb_user
        self.graphdb_password = graphdb_password
        self._llm_client = llm_client
        self._embedder = embedder
        self.embedding_model = str(embedding_model or "").strip() or None
        self.enable_otel_tracing = enable_otel_tracing
        self.oracle_connection = oracle_connection
        self.graphiti_db = str(
            graphiti_db or ("oracle" if oracle_connection is not None else "neo4j")
        ).strip().lower()

        self._graphiti = None
        self._initialized = False
        self.client: GraphitiOraclePGClient | None = None

        self._graph_metadata: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def _normalize_graph_id(cls, graph_id: Any) -> str:
        return str(graph_id or "").strip()

    @classmethod
    def _set_cached_ontology(
        cls,
        graph_id: str,
        entities: Optional[Dict[str, Any]],
        edges: Optional[Dict[str, Any]],
    ) -> None:
        normalized_graph_id = cls._normalize_graph_id(graph_id)
        if not normalized_graph_id:
            return

        ontology_entry = {
            "entities": dict(entities or {}),
            "edges": dict(edges or {}),
        }

        with cls._ontology_cache_lock:
            if normalized_graph_id in cls._ontology_cache:
                cls._ontology_cache.pop(normalized_graph_id, None)
            cls._ontology_cache[normalized_graph_id] = ontology_entry
            cls._ontology_cache.move_to_end(normalized_graph_id)
            while len(cls._ontology_cache) > cls._ONTOLOGY_CACHE_MAX_SIZE:
                cls._ontology_cache.popitem(last=False)

    @classmethod
    def _get_cached_ontology(cls, graph_id: str) -> Dict[str, Any]:
        normalized_graph_id = cls._normalize_graph_id(graph_id)
        if not normalized_graph_id:
            return {}

        with cls._ontology_cache_lock:
            ontology_entry = cls._ontology_cache.get(normalized_graph_id)
            if ontology_entry is None:
                return {}
            cls._ontology_cache.move_to_end(normalized_graph_id)
            return ontology_entry

    @classmethod
    def _remove_cached_ontology(cls, graph_id: str) -> None:
        normalized_graph_id = cls._normalize_graph_id(graph_id)
        if not normalized_graph_id:
            return
        with cls._ontology_cache_lock:
            cls._ontology_cache.pop(normalized_graph_id, None)

    def _sync_cached_ontology_to_client(self) -> None:
        if self.client is None:
            return
        with self._ontology_cache_lock:
            ontology_items = list(self._ontology_cache.items())
        for graph_id, ontology_entry in ontology_items:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=ontology_entry.get("entities"),
                edges=ontology_entry.get("edges"),
            )

    def _ensure_graph_constraints(self, graph_id: str) -> None:
        """Ensure Graphiti is initialized before graph-scoped operations.

        Indices and constraints are created once in ``_ensure_initialized`` for the
        whole Neo4j database or Oracle PG project (Graphiti driver scope). They are not
        per logical ``group_id``/graph_id; re-running DDL for each new graph caused
        redundant locks.
        """
        if not self._normalize_graph_id(graph_id):
            return
        self._ensure_initialized()

    def _ensure_initialized(self):
        if self._initialized:
            return

        try:
            llm_client = self._llm_client
            if llm_client is None:
                llm_client = self._build_default_llm_client()

            embedder = self._embedder
            if embedder is None:
                embedder = self._build_default_embedder()

            graphiti_tracer = create_graphiti_langfuse_tracer(
                enable_for_request=self.enable_otel_tracing
            )
            if self.graphiti_db == "oracle":
                if self.oracle_connection is None:
                    raise ValueError("Oracle Graphiti mode requires oracle_connection")
                self.client = GraphitiOraclePGClient.from_config(
                    self.oracle_connection,
                    llm_client=llm_client,
                    embedder=embedder,
                    tracer=graphiti_tracer,
                    trace_span_prefix="graphiti.oracle",
                    run_async=_run_async,
                )
                self._graphiti = self.client.client
            else:
                from graphiti_core import Graphiti

                self._graphiti = Graphiti(
                    self.graphdb_uri,
                    self.graphdb_user,
                    self.graphdb_password,
                    llm_client=llm_client,
                    embedder=embedder,
                    tracer=graphiti_tracer,
                    trace_span_prefix="graphiti",
                )
                self.client = GraphitiOraclePGClient(self._graphiti, run_async=_run_async)

            self._sync_cached_ontology_to_client()

            self._initialized = True
            logger.info("Graphiti client initialized")

        except ImportError as e:
            raise ImportError(
                "graphiti-core is not installed. Please run: pip install graphiti-core"
            ) from e
        except Exception as e:
            logger.error(f"Graphiti initialization failed: {e}")
            raise

    def _build_default_llm_client(self) -> Any:
        from graphiti_core.llm_client.config import LLMConfig

        from app.core.llm.providers.openai.provider import GraphitiOpenAIGenericClient

        api_key = os.environ.get('LLM_API_KEY')
        base_url = os.environ.get('LLM_BASE_URL')
        model = os.environ.get('GRAPHITI_LLM_MODEL') or os.environ.get('LLM_MODEL_NAME')
        small_model = os.environ.get('GRAPHITI_LLM_SMALL_MODEL') or None

        temperature = float(os.environ.get('GRAPHITI_LLM_TEMPERATURE', '0') or '0')
        max_tokens = int(os.environ.get('GRAPHITI_LLM_MAX_TOKENS', '50000') or '50000')

        config = LLMConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            small_model=small_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        llm_client = GraphitiOpenAIGenericClient(config=config, max_tokens=max_tokens)
        return llm_client

    def _build_default_embedder(self) -> Any:
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

        api_key = os.environ.get('GRAPHITI_EMBEDDING_API_KEY')
        base_url = os.environ.get('GRAPHITI_EMBEDDING_BASE_URL')
        embedding_model = self.embedding_model or Config.GRAPHITI_DEFAULT_EMBEDDING_MODEL

        if embedding_model:
            config = OpenAIEmbedderConfig(
                api_key=api_key,
                base_url=base_url,
                embedding_model=embedding_model,
            )
        else:
            config = OpenAIEmbedderConfig(
                api_key=api_key,
                base_url=base_url,
            )

        base_embedder = OpenAIEmbedder(config=config)

        if self._is_openai_compatible_only():
            logger.info("Detected non-standard OpenAI API, enabling DashScope Embedder chunk processing")
            return _create_dashscope_embedder_wrapper(base_embedder, max_batch_size=10)

        return base_embedder

    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        self._ensure_graph_constraints(graph_id)
        self.client.graph.create(graph_id=graph_id, name=name, description=description)
        self._graph_metadata[graph_id] = {
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"Graph metadata recorded: graph_id={graph_id}, name={name}")

    def delete_graph(self, graph_id: str) -> None:
        self._ensure_initialized()
        self.client.graph.delete(graph_id=graph_id)

        self._graph_metadata.pop(graph_id, None)
        self._remove_cached_ontology(graph_id)
        logger.info(f"Graph has been deleted: graph_id={graph_id}")

    def set_ontology(
        self,
        graph_ids: List[str],
        entities: Optional[Dict[str, Any]] = None,
        edges: Optional[Dict[str, Any]] = None
    ) -> None:
        for graph_id in graph_ids:
            normalized_graph_id = self._normalize_graph_id(graph_id)
            if not normalized_graph_id:
                continue

            self._set_cached_ontology(normalized_graph_id, entities, edges)
            if self._initialized and self.client is not None:
                self.client.graph.set_ontology(
                    graph_ids=[normalized_graph_id],
                    entities=entities,
                    edges=edges,
                )
            logger.info(
                f"Ontology has been cached (MVP no-op): graph_id={normalized_graph_id}, "
                f"entity_types={len(entities or {})}, edge_types={len(edges or {})}"
            )

    # ==================== Episode operations ====================

    def add_episode(self, graph_id: str, data: str, episode_type: str = "text") -> str:
        self._ensure_initialized()
        episode = self.client.graph.add(
            graph_id=graph_id,
            data=data,
            type=episode_type,
            source_description=f"{graph_id}_episodes",
        )
        return episode.uuid

    def add_episode_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, Any]]
    ) -> List[str]:
        self._ensure_initialized()
        added_episodes = self.client.graph.add_batch(graph_id=graph_id, episodes=episodes)
        return [episode.uuid for episode in added_episodes]

    def get_episode_status(self, episode_uuid: str) -> EpisodeStatus:
        return EpisodeStatus(uuid=episode_uuid, processed=True)

    def wait_for_episode(self, episode_uuid: str, timeout: int = 300) -> bool:
        return True

    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        self._ensure_initialized()
        raw_nodes = self.client.graph.node.get_by_graph_id(graph_id=graph_id)
        if not raw_nodes:
            logger.debug("get_all_nodes: no nodes found for group_id=%s", graph_id)
        return [self._graphiti_node_to_graph_node(node) for node in raw_nodes]

    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        self._ensure_initialized()
        try:
            raw_node = self.client.graph.node.get(uuid_=node_uuid)
        except Exception as exc:
            logger.debug("get_node lookup failed for uuid=%s: %s", node_uuid, exc)
            raw_node = None
        if raw_node is None:
            logger.debug(f"get_node: No node found for uuid={node_uuid}")
            return None

        return self._graphiti_node_to_graph_node(raw_node)

    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        self._ensure_initialized()
        raw_edges = self.client.graph.node.get_entity_edges(node_uuid=node_uuid)
        if not raw_edges:
            logger.debug(f"get_node_edges: no edges found for node uuid={node_uuid}")
        return [self._graphiti_edge_to_graph_edge(edge) for edge in raw_edges]

    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        self._ensure_initialized()
        raw_edges = self.client.graph.edge.get_by_graph_id(graph_id=graph_id)
        if not raw_edges:
            logger.debug("get_all_edges: no edges found for group_id=%s", graph_id)
        return [self._graphiti_edge_to_graph_edge(edge) for edge in raw_edges]

    def _is_openai_compatible_only(self) -> bool:
        # force use cross_encoder
        if os.environ.get('GRAPHITI_FORCE_CROSS_ENCODER', '').lower() in ('true', '1', 'yes'):
            return False

        base_url = os.environ.get('OPENAI_BASE_URL', '')

        if not base_url or 'api.openai.com' in base_url or 'openai' in base_url:
            return False

        non_standard_indicators = [
            'dashscope', 'aliyun', 'azure', 'localhost',
            'ollama', 'vllm', 'lmstudio', 'openrouter'
        ]
        return any(indicator in base_url.lower() for indicator in non_standard_indicators)

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: str = "rrf"  # Safer default.
    ) -> SearchResult:
        self._ensure_initialized()
        if reranker == "cross_encoder" and self._is_openai_compatible_only():
            logger.info("Detected non-standard OpenAI API, cross_encoder downgraded to rrf")
            reranker = "rrf"

        result = self.client.graph.search(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope,
            reranker=reranker,
        )
        raw_nodes = result.nodes
        raw_edges = result.edges

        if not raw_nodes and not raw_edges:
            logger.debug(f"search: query='{query}' group_id={graph_id} no results")

        nodes = [self._graphiti_node_to_graph_node(n) for n in raw_nodes]
        edges = [self._graphiti_edge_to_graph_edge(e) for e in raw_edges]

        return SearchResult(nodes=nodes, edges=edges)


    def _graphiti_node_to_graph_node(self, node: Any) -> GraphNode:
        """Convert Graphiti node object to GraphNode"""
        created_at = getattr(node, 'created_at', None)
        if hasattr(created_at, 'isoformat'):
            created_at = created_at.isoformat()
        elif created_at:
            created_at = str(created_at)

        return GraphNode(
            uuid=getattr(node, 'uuid', ''),
            name=getattr(node, 'name', ''),
            labels=getattr(node, 'labels', ['Entity']),
            summary=getattr(node, 'summary', ''),
            attributes=getattr(node, 'attributes', {}),
            created_at=created_at,
        )

    def _graphiti_edge_to_graph_edge(self, edge: Any) -> GraphEdge:
        """Convert Graphiti edge object to GraphEdge"""
        def _format_time(t):
            if t is None:
                return None
            if hasattr(t, 'isoformat'):
                return t.isoformat()
            return str(t)

        return GraphEdge(
            uuid=getattr(edge, 'uuid', ''),
            name=getattr(edge, 'name', '') or getattr(edge, 'fact_type', ''),
            fact=getattr(edge, 'fact', ''),
            source_node_uuid=getattr(edge, 'source_node_uuid', ''),
            target_node_uuid=getattr(edge, 'target_node_uuid', ''),
            attributes=getattr(edge, 'attributes', {}),
            created_at=_format_time(getattr(edge, 'created_at', None)),
            valid_at=_format_time(getattr(edge, 'valid_at', None)),
            invalid_at=_format_time(getattr(edge, 'invalid_at', None)),
            expired_at=_format_time(getattr(edge, 'expired_at', None)),
            episodes=getattr(edge, 'episodes', []),
            fact_type=getattr(edge, 'fact_type', '') or getattr(edge, 'name', ''),
        )

    def close(self):
        if self._graphiti:
            _run_async(self._graphiti.close())
            self._initialized = False
            logger.info("Graphiti connection has been closed")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
