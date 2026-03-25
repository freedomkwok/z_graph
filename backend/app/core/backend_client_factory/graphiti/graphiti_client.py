import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.core.backend_client_factory.schema import (
    ZepClientAdapter,
    GraphNode,
    GraphEdge,
    SearchResult,
    EpisodeStatus,
)
from app.core.utils.langfuse import create_graphiti_langfuse_tracer
from graphiti_core.driver.driver import GraphDriver
logger = logging.getLogger('zep_graph.graphiti_client')

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
    return future.result(timeout=300)  # Timeout is 5 minutes

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
    def __init__(
        self,
        graphdb_uri: str,
        graphdb_user: str,
        graphdb_password: str,
        llm_client: Optional[Any] = None,
        embedder: Optional[Any] = None,
        graph_driver: GraphDriver | None = None,
    ):
        self.graphdb_uri = graphdb_uri
        self.graphdb_user = graphdb_user
        self.graphdb_password = graphdb_password
        self._llm_client = llm_client
        self._embedder = embedder
        self.graph_driver = graph_driver

        self._graphiti = None
        self._driver = None
        self._initialized = False

        self._graph_metadata: Dict[str, Dict[str, Any]] = {}
        self._ontology_cache: Dict[str, Dict[str, Any]] = {}

    def _ensure_initialized(self):
        if self._initialized:
            return

        try:
            from graphiti_core import Graphiti
            from app.core.backend_client_factory.graphiti.patcher import apply_patch

            apply_patch() # sanitization patch (Issue #683 workaround)

            llm_client = self._llm_client
            if llm_client is None:
                llm_client = self._build_default_llm_client()

            embedder = self._embedder
            if embedder is None:
                embedder = self._build_default_embedder()

            if self.graph_driver is not None:
                self._graphiti = Graphiti(
                    llm_client=llm_client,
                    embedder=embedder,
                    graph_driver=self.graph_driver,
                )
            else:
                self._graphiti = Graphiti(
                    self.graphdb_uri,
                    self.graphdb_user,
                    self.graphdb_password,
                    llm_client=llm_client,
                    embedder=embedder,
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
        max_tokens = int(os.environ.get('GRAPHITI_LLM_MAX_TOKENS', '8192') or '8192')

        config = LLMConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
            small_model=small_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        llm_client = GraphitiOpenAIGenericClient(config=config, max_tokens=max_tokens)
        tracer = create_graphiti_langfuse_tracer()
        if tracer is not None and hasattr(llm_client, "set_tracer"):
            try:
                llm_client.set_tracer(tracer)
                logger.info("Langfuse tracer has been attached to Graphiti LLM client")
            except Exception as exc:
                logger.warning("Failed to attach Langfuse tracer to Graphiti LLM client: %s", exc)
        return llm_client

    def _build_default_embedder(self) -> Any:
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig

        api_key = os.environ.get('GRAPHITI_EMBEDDING_API_KEY')
        base_url = os.environ.get('GRAPHITI_EMBEDDING_BASE_URL')
        embedding_model = os.environ.get('GRAPHITI_EMBEDDING_MODEL')

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
        logger.info(f"Graph metadata recorded: graph_id={graph_id}, name={name}")

    def delete_graph(self, graph_id: str) -> None:
        self._ensure_initialized()

        async def _delete():
            records, _, _ = await self._driver.execute_query(
                """
                MATCH (n {group_id: $group_id})
                DETACH DELETE n
                RETURN count(n) as deleted_count
                """,
                group_id=graph_id,
            )
            deleted = records[0]['deleted_count'] if records else 0
            logger.debug(f"Deleted {deleted} nodes (group_id={graph_id})")

        _run_async(_delete())

        self._graph_metadata.pop(graph_id, None)
        self._ontology_cache.pop(graph_id, None)
        logger.info(f"Graph has been deleted: graph_id={graph_id}")

    def set_ontology(
        self,
        graph_ids: List[str],
        entities: Optional[Dict[str, Any]] = None,
        edges: Optional[Dict[str, Any]] = None
    ) -> None:
        for graph_id in graph_ids:
            self._ontology_cache[graph_id] = {
                "entities": entities or {},
                "edges": edges or {},
            }
            logger.info(
                f"Ontology has been cached (MVP no-op): graph_id={graph_id}, "
                f"entity_types={len(entities or {})}, edge_types={len(edges or {})}"
            )

    # ==================== Episode operations ====================

    def add_episode(self, graph_id: str, data: str, episode_type: str = "text") -> str:
        self._ensure_initialized()

        from graphiti_core.nodes import EpisodeType

        # Map episode_type.
        source_type = EpisodeType.text
        if episode_type == "message":
            source_type = EpisodeType.message
        elif episode_type == "json":
            source_type = EpisodeType.json

        async def _add():
            result = await self._graphiti.add_episode(
                name=f"episode_{graph_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                episode_body=data,
                source=source_type,
                source_description="mirofish_simulation",
                reference_time=datetime.now(timezone.utc),
                group_id=graph_id,
            )
            return result.episode.uuid if result and result.episode else ""

        return _run_async(_add())

    def add_episode_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, Any]]
    ) -> List[str]:
        self._ensure_initialized()

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
                    source_description="mirofish_simulation",
                    reference_time=datetime.now(timezone.utc),
                )
            )

        async def _add_bulk():
            result = await self._graphiti.add_episode_bulk(
                bulk_episodes=raw_episodes,
                group_id=graph_id,
            )
            # Return all episode UUIDs.
            return [ep.uuid for ep in result.episodes] if result and result.episodes else []

        return _run_async(_add_bulk())

    def get_episode_status(self, episode_uuid: str) -> EpisodeStatus:
        return EpisodeStatus(uuid=episode_uuid, processed=True)

    def wait_for_episode(self, episode_uuid: str, timeout: int = 300) -> bool:
        return True

    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        self._ensure_initialized()

        async def _get_nodes():
            for label in ["Entity", "EntityNode"]:
                records, _, _ = await self._driver.execute_query(
                    f"""
                    MATCH (n:{label} {{group_id: $group_id}})
                    RETURN
                        n.uuid AS uuid,
                        n.name AS name,
                        labels(n) AS labels,
                        n.summary AS summary,
                        properties(n) AS props,
                        n.created_at AS created_at
                    """,
                    group_id=graph_id,
                )
                if records:
                    return records

            logger.warning(
                f"get_all_nodes: No nodes found for group_id={graph_id}. "
                f"Possible reasons: 1) Graph is empty 2) Graphiti schema mismatch (tried Entity, EntityNode)"
            )
            return []

        records = _run_async(_get_nodes())
        nodes = []
        for record in records:
            props = record.get("props", {})
            attributes = {
                k: v for k, v in props.items()
                if k not in ["uuid", "name", "summary", "created_at", "group_id"]
            }
            created_at = record.get("created_at")
            if hasattr(created_at, 'to_native'):
                created_at = created_at.to_native().isoformat()
            elif created_at:
                created_at = str(created_at)

            nodes.append(GraphNode(
                uuid=record.get("uuid", ""),
                name=record.get("name", ""),
                labels=record.get("labels", ["Entity"]),
                summary=record.get("summary", ""),
                attributes=attributes,
                created_at=created_at,
            ))
        return nodes

    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        self._ensure_initialized()

        async def _get_node():
            records, _, _ = await self._driver.execute_query(
                """
                MATCH (n {uuid: $uuid})
                RETURN
                    n.uuid AS uuid,
                    n.name AS name,
                    labels(n) AS labels,
                    n.summary AS summary,
                    properties(n) AS props,
                    n.created_at AS created_at
                LIMIT 1
                """,
                uuid=node_uuid,
            )
            return records

        records = _run_async(_get_node())
        if not records:
            logger.debug(f"get_node: No node found for uuid={node_uuid}")
            return None

        record = records[0]
        props = record.get("props", {})
        attributes = {
            k: v for k, v in props.items()
            if k not in ["uuid", "name", "summary", "created_at", "group_id"]
        }
        created_at = record.get("created_at")
        if hasattr(created_at, 'to_native'):
            created_at = created_at.to_native().isoformat()
        elif created_at:
            created_at = str(created_at)

        return GraphNode(
            uuid=record.get("uuid", ""),
            name=record.get("name", ""),
            labels=record.get("labels", ["Entity"]),
            summary=record.get("summary", ""),
            attributes=attributes,
            created_at=created_at,
        )

    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        self._ensure_initialized()

        async def _get_edges():
            # add all edges for the node
            # use r.name if available, otherwise use type(r)
            records, _, _ = await self._driver.execute_query(
                """
                MATCH (n {uuid: $uuid})-[r]-(m)
                RETURN DISTINCT
                    r.uuid AS uuid,
                    COALESCE(r.name, type(r)) AS name,
                    r.fact AS fact,
                    startNode(r).uuid AS source_uuid,
                    endNode(r).uuid AS target_uuid,
                    properties(r) AS props,
                    r.created_at AS created_at,
                    r.valid_at AS valid_at,
                    r.invalid_at AS invalid_at,
                    r.expired_at AS expired_at
                """,
                uuid=node_uuid,
            )
            return records

        records = _run_async(_get_edges())
        if not records:
            logger.debug(f"get_node_edges: no edges found for node uuid={node_uuid}")
        return [self._record_to_edge(record) for record in records]

    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        self._ensure_initialized()

        async def _get_edges():
            # Filter edges by node group_id and use DISTINCT to avoid duplicates.
            # Note: edges themselves may not have group_id, so filter via connected nodes.
            # Prefer r.name (actual relation name), fallback to type(r) (relation type).
            for label in ["Entity", "EntityNode"]:
                records, _, _ = await self._driver.execute_query(
                    f"""
                    MATCH (n:{label} {{group_id: $group_id}})-[r]-(m:{label})
                    WHERE n.group_id = m.group_id
                    RETURN DISTINCT
                        r.uuid AS uuid,
                        COALESCE(r.name, type(r)) AS name,
                        r.fact AS fact,
                        startNode(r).uuid AS source_uuid,
                        endNode(r).uuid AS target_uuid,
                        properties(r) AS props,
                        r.created_at AS created_at,
                        r.valid_at AS valid_at,
                        r.invalid_at AS invalid_at,
                        r.expired_at AS expired_at
                    """,
                    group_id=graph_id,
                )
                if records:
                    return records

            logger.warning(
                f"get_all_edges: No edges found for group_id={graph_id}. "
                f"Possible reasons: 1) Graph is empty 2) Graphiti schema mismatch"
            )
            return []

        records = _run_async(_get_edges())
        return [self._record_to_edge(record) for record in records]

    def _is_openai_compatible_only(self) -> bool:
        # force use cross_encoder
        if os.environ.get('GRAPHITI_FORCE_CROSS_ENCODER', '').lower() in ('true', '1', 'yes'):
            return False

        base_url = os.environ.get('OPENAI_BASE_URL', '')

        if not base_url or 'api.openai.com' in base_url:
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
        self._ensure_initialized()
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


    def _record_to_edge(self, record: Dict[str, Any]) -> GraphEdge:
        """Convert Neo4j query result to GraphEdge"""
        props = record.get("props", {})
        attributes = {
            k: v for k, v in props.items()
            if k not in ["uuid", "fact", "created_at", "valid_at", "invalid_at", "expired_at", "group_id"]
        }

        def _format_time(t):
            if t is None:
                return None
            if hasattr(t, 'to_native'):
                return t.to_native().isoformat()
            return str(t)

        return GraphEdge(
            uuid=record.get("uuid", ""),
            name=record.get("name", ""),
            fact=record.get("fact", ""),
            source_node_uuid=record.get("source_uuid", ""),
            target_node_uuid=record.get("target_uuid", ""),
            attributes=attributes,
            created_at=_format_time(record.get("created_at")),
            valid_at=_format_time(record.get("valid_at")),
            invalid_at=_format_time(record.get("invalid_at")),
            expired_at=_format_time(record.get("expired_at")),
            episodes=[],  # Graphiti edges may not expose episodes.
            fact_type=record.get("name", ""),
        )

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
