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
import inspect
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.core.config import Config
from app.core.backend_client_factory.schema import (
    ZepClientAdapter,
    GraphNode,
    GraphEdge,
    SearchResult,
    EpisodeStatus,
)
from app.core.utils.langfuse import create_graphiti_langfuse_tracer
from graphiti_core.driver.driver import GraphDriver
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
        graph_driver: GraphDriver | None = None,
        embedding_model: str | None = None,
        enable_otel_tracing: bool | None = None,
    ):
        self.graphdb_uri = graphdb_uri
        self.graphdb_user = graphdb_user
        self.graphdb_password = graphdb_password
        self._llm_client = llm_client
        self._embedder = embedder
        self.graph_driver = graph_driver
        self.embedding_model = str(embedding_model or "").strip() or None
        self.enable_otel_tracing = enable_otel_tracing

        self._graphiti = None
        self._driver = None
        self._initialized = False

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
            from graphiti_core import Graphiti
            # from app.core.backend_client_factory.graphiti.patcher import apply_patch

            # apply_patch() # sanitization patch (Issue #683 workaround)

            llm_client = self._llm_client
            if llm_client is None:
                llm_client = self._build_default_llm_client()

            embedder = self._embedder
            if embedder is None:
                embedder = self._build_default_embedder()

            graphiti_tracer = create_graphiti_langfuse_tracer(
                enable_for_request=self.enable_otel_tracing
            )
            trace_span_prefix = "graphiti.oracle" if self.graph_driver is not None else "graphiti"

            if self.graph_driver is not None:
                self._graphiti = Graphiti(
                    llm_client=llm_client,
                    embedder=embedder,
                    graph_driver=self.graph_driver,
                    tracer=graphiti_tracer,
                    trace_span_prefix=trace_span_prefix,
                )
            else:
                self._graphiti = Graphiti(
                    self.graphdb_uri,
                    self.graphdb_user,
                    self.graphdb_password,
                    llm_client=llm_client,
                    embedder=embedder,
                    tracer=graphiti_tracer,
                    trace_span_prefix=trace_span_prefix,
                )

            _run_async(self._graphiti.build_indices_and_constraints())

            self._driver = self._graphiti.driver

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
        self._graph_metadata[graph_id] = {
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._ensure_graph_constraints(graph_id)
        logger.info(f"Graph metadata recorded: graph_id={graph_id}, name={name}")

    def delete_graph(self, graph_id: str) -> None:
        self._ensure_graph_constraints(graph_id)

        async def _delete():
            graph_ops = self._driver.graph_ops
            if graph_ops is not None:
                await graph_ops.clear_data(self._driver, [graph_id])
                logger.debug("Cleared graph data via driver graph_ops (group_id=%s)", graph_id)
            else:
                from graphiti_core.utils.maintenance.graph_data_operations import clear_data

                await clear_data(self._driver, [graph_id])
                logger.debug("Cleared graph data via graph_data_operations.clear_data (group_id=%s)", graph_id)

        _run_async(_delete())

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
            self._ensure_graph_constraints(graph_id)
            self._set_cached_ontology(graph_id, entities, edges)
            logger.info(
                f"Ontology has been cached (MVP no-op): graph_id={graph_id}, "
                f"entity_types={len(entities or {})}, edge_types={len(edges or {})}"
            )

    @staticmethod
    def _extract_source_target_pair(source_target: Any) -> tuple[str, str] | None:
        if isinstance(source_target, dict):
            source = str(source_target.get("source", "")).strip()
            target = str(source_target.get("target", "")).strip()
        else:
            source = str(getattr(source_target, "source", "")).strip()
            target = str(getattr(source_target, "target", "")).strip()
        if source and target:
            return source, target
        return None

    def _build_ontology_kwargs(self, graph_id: str) -> Dict[str, Any]:
        ontology_entry = self._get_cached_ontology(graph_id)
        if not isinstance(ontology_entry, dict):
            return {}

        entity_types = ontology_entry.get("entities")
        if not isinstance(entity_types, dict):
            entity_types = {}

        edges = ontology_entry.get("edges")
        if not isinstance(edges, dict):
            edges = {}

        edge_types: Dict[str, Any] = {}
        edge_type_map: Dict[tuple[str, str], List[str]] = {}

        for edge_name, edge_definition in edges.items():
            normalized_edge_name = str(edge_name or "").strip()
            if not normalized_edge_name:
                continue

            edge_class: Any = None
            source_targets: list[Any] = []

            if isinstance(edge_definition, tuple) and len(edge_definition) >= 2:
                edge_class = edge_definition[0]
                source_targets = list(edge_definition[1] or [])
            elif isinstance(edge_definition, dict):
                edge_class = edge_definition.get("edge_type") or edge_definition.get("model")
                source_targets = list(edge_definition.get("source_targets", []) or [])
            else:
                edge_class = edge_definition

            if edge_class is not None:
                edge_types[normalized_edge_name] = edge_class

            for source_target in source_targets:
                pair = self._extract_source_target_pair(source_target)
                if pair is None:
                    continue
                if pair not in edge_type_map:
                    edge_type_map[pair] = []
                if normalized_edge_name not in edge_type_map[pair]:
                    edge_type_map[pair].append(normalized_edge_name)

        ontology_kwargs: Dict[str, Any] = {}
        if entity_types:
            ontology_kwargs["entity_types"] = entity_types
        if edge_types:
            ontology_kwargs["edge_types"] = edge_types
        if edge_type_map:
            ontology_kwargs["edge_type_map"] = edge_type_map
        return ontology_kwargs

    @staticmethod
    def _filter_supported_kwargs(func: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return kwargs

        parameters = signature.parameters
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
            return kwargs

        supported_names = set(parameters.keys())
        return {key: value for key, value in kwargs.items() if key in supported_names}

    # ==================== Episode operations ====================

    def add_episode(self, graph_id: str, data: str, episode_type: str = "text") -> str:
        self._ensure_graph_constraints(graph_id)

        from graphiti_core.nodes import EpisodeType

        # Map episode_type.
        source_type = EpisodeType.text
        if episode_type == "message":
            source_type = EpisodeType.message
        elif episode_type == "json":
            source_type = EpisodeType.json

        async def _add():
            call_kwargs = {
                "name": f"episode_{graph_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "episode_body": data,
                "source": source_type,
                "source_description": f"{graph_id}_episodes",
                "reference_time": datetime.now(timezone.utc),
                "group_id": graph_id,
            }
            call_kwargs.update(self._build_ontology_kwargs(graph_id))
            filtered_kwargs = self._filter_supported_kwargs(self._graphiti.add_episode, call_kwargs)
            result = await self._graphiti.add_episode(**filtered_kwargs)
            return result.episode.uuid if result and result.episode else ""

        return _run_async(_add())

    def add_episode_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, Any]]
    ) -> List[str]:
        self._ensure_graph_constraints(graph_id)

        from graphiti_core.nodes import EpisodeType
        from graphiti_core.utils.bulk_utils import RawEpisode

        raw_episodes = []
        for i, ep in enumerate(episodes):
            ep_type = ep.get("type", "text")
            source_type = EpisodeType.text
            if ep_type == "message":
                source_type = EpisodeType.message
            elif ep_type == "json":
                source_type = EpisodeType.json

            raw_episodes.append(
                RawEpisode(
                    name=f"episode_{graph_id}_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    content=ep.get("data", ""),
                    source=source_type,
                    source_description=f"{graph_id}_episodes",
                    reference_time=datetime.now(timezone.utc),
                )
            )

        async def _add_bulk():
            call_kwargs = {
                "bulk_episodes": raw_episodes,
                "group_id": graph_id,
            }
            call_kwargs.update(self._build_ontology_kwargs(graph_id))
            filtered_kwargs = self._filter_supported_kwargs(self._graphiti.add_episode_bulk, call_kwargs)
            result = await self._graphiti.add_episode_bulk(**filtered_kwargs)
            # Return all episode UUIDs.
            return [ep.uuid for ep in result.episodes] if result and result.episodes else []

        return _run_async(_add_bulk())

    def get_episode_status(self, episode_uuid: str) -> EpisodeStatus:
        return EpisodeStatus(uuid=episode_uuid, processed=True)

    def wait_for_episode(self, episode_uuid: str, timeout: int = 300) -> bool:
        return True

    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        self._ensure_graph_constraints(graph_id)

        async def _get_nodes():
            node_ops = self._driver.entity_node_ops
            if node_ops is None:
                logger.warning("get_all_nodes: entity_node_ops is unavailable for this driver")
                return []
            return await node_ops.get_by_group_ids(self._driver, [graph_id])

        raw_nodes = _run_async(_get_nodes())
        if not raw_nodes:
            logger.debug("get_all_nodes: no nodes found for group_id=%s", graph_id)
        return [self._graphiti_node_to_graph_node(node) for node in raw_nodes]

    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        async def _get_node():
            node_ops = self._driver.entity_node_ops
            if node_ops is None:
                logger.warning("get_node: entity_node_ops is unavailable for this driver")
                return None
            try:
                return await node_ops.get_by_uuid(self._driver, node_uuid)
            except Exception as exc:
                logger.debug("get_node lookup failed for uuid=%s: %s", node_uuid, exc)
                return None

        raw_node = _run_async(_get_node())
        if raw_node is None:
            logger.debug(f"get_node: No node found for uuid={node_uuid}")
            return None

        return self._graphiti_node_to_graph_node(raw_node)

    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        async def _get_edges():
            edge_ops = self._driver.entity_edge_ops
            if edge_ops is None:
                logger.warning("get_node_edges: entity_edge_ops is unavailable for this driver")
                return []
            return await edge_ops.get_by_node_uuid(self._driver, node_uuid)

        raw_edges = _run_async(_get_edges())
        if not raw_edges:
            logger.debug(f"get_node_edges: no edges found for node uuid={node_uuid}")
        return [self._graphiti_edge_to_graph_edge(edge) for edge in raw_edges]

    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        self._ensure_graph_constraints(graph_id)

        async def _get_edges():
            edge_ops = self._driver.entity_edge_ops
            if edge_ops is None:
                logger.warning("get_all_edges: entity_edge_ops is unavailable for this driver")
                return []
            return await edge_ops.get_by_group_ids(self._driver, [graph_id])

        raw_edges = _run_async(_get_edges())
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
        """
        Use Graphiti's public search_() API (with config) for search.
        If search_() is not available, fallback to simple search() API.
        Note: reranker="cross_encoder" requires OpenAI API to support logprobs,
        non-standard API (e.g. DashScope) will automatically downgrade to rrf.
        """
        self._ensure_graph_constraints(graph_id)
        from graphiti_core.search.search_config_recipes import (
            COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
            EDGE_HYBRID_SEARCH_RRF,
            NODE_HYBRID_SEARCH_RRF,
        )

        if reranker == "cross_encoder" and self._is_openai_compatible_only():
            logger.info("Detected non-standard OpenAI API, cross_encoder downgraded to rrf")
            reranker = "rrf"

        async def _do_search():
            nodes = []
            edges = []

            has_search_method = hasattr(self._graphiti, 'search_')

            if not has_search_method:
                logger.info("Using graphiti.search() simple API (search_() is not available)")
                try:
                    results = await self._graphiti.search(
                        query=query,
                        group_ids=[graph_id],
                        num_results=limit,
                    )
                    if results:
                        edges = list(results) if not isinstance(results, list) else results
                    return nodes, edges
                except Exception as e:
                    logger.warning(f"graphiti.search() failed: {e}, returning empty results")
                    return [], []

            try:
                if scope == "nodes":
                    config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                    config.limit = limit
                    result = await self._graphiti.search_(
                        query=query,
                        config=config,
                        group_ids=[graph_id],
                    )
                    if result and hasattr(result, 'nodes'):
                        nodes = result.nodes or []

                elif scope == "edges":
                    config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                    config.limit = limit
                    result = await self._graphiti.search_(
                        query=query,
                        config=config,
                        group_ids=[graph_id],
                    )
                    if result and hasattr(result, 'edges'):
                        edges = result.edges or []

                else:  # both
                    if reranker == "cross_encoder":
                        config = COMBINED_HYBRID_SEARCH_CROSS_ENCODER.model_copy(deep=True)
                        config.limit = limit
                        result = await self._graphiti.search_(
                            query=query,
                            config=config,
                            group_ids=[graph_id],
                        )
                        if result:
                            nodes = result.nodes or [] if hasattr(result, 'nodes') else []
                            edges = result.edges or [] if hasattr(result, 'edges') else []
                    else:
                        node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                        node_config.limit = limit // 2
                        edge_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
                        edge_config.limit = limit // 2

                        node_result = await self._graphiti.search_(
                            query=query, config=node_config, group_ids=[graph_id]
                        )
                        edge_result = await self._graphiti.search_(
                            query=query, config=edge_config, group_ids=[graph_id]
                        )

                        if node_result and hasattr(node_result, 'nodes'):
                            nodes = node_result.nodes or []
                        if edge_result and hasattr(edge_result, 'edges'):
                            edges = edge_result.edges or []

            except Exception as e:
                logger.warning(f"graphiti.search_() failed: {e}, trying fallback")
                try:
                    results = await self._graphiti.search(
                        query=query,
                        group_ids=[graph_id],
                        num_results=limit,
                    )
                    if results:
                        edges = list(results) if not isinstance(results, list) else results
                except Exception as fallback_e:
                    logger.error(f"search fallback failed: {fallback_e}")

            return nodes, edges

        raw_nodes, raw_edges = _run_async(_do_search())

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
