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

import logging
import threading
import time
from typing import Optional

from app.core.config import Config
from app.core.backend_client_factory.schema import ZepClientAdapter
from app.core.backend_client_factory.zep.zep_client import ZepCloudClient
from app.core.backend_client_factory.graphiti.graphiti_client import GraphitiClient
logger = logging.getLogger('z_graph.zep_factory')

CLIENT_PROFILE_BUILD_GRAPH = "build_graph"
CLIENT_PROFILE_NON_BUILD_GRAPH = "non_build_graph"
SUPPORTED_CLIENT_PROFILES = {
    CLIENT_PROFILE_BUILD_GRAPH,
    CLIENT_PROFILE_NON_BUILD_GRAPH,
}
CLIENT_IDLE_TTL_SECONDS = 30 * 60
NON_BUILD_ORACLE_POOL_MIN = 1
NON_BUILD_ORACLE_POOL_MAX = 4
NON_BUILD_ORACLE_POOL_INCREMENT = 1
NON_BUILD_ORACLE_MAX_COROUTINES = 5

_client_cache: dict[tuple[object, ...], ZepClientAdapter] = {}
_client_last_access: dict[tuple[object, ...], float] = {}
_client_lock = threading.Lock()


def _normalize_client_profile(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_CLIENT_PROFILES:
        return normalized
    return CLIENT_PROFILE_NON_BUILD_GRAPH


def _close_client_safely(client: ZepClientAdapter | None) -> None:
    if client is None:
        return
    if not hasattr(client, "close"):
        return
    try:
        client.close()
    except Exception:
        logger.exception("Failed to close cached Zep client")


def _evict_idle_clients_locked(now: float) -> None:
    expired_keys = [
        key
        for key, last_access in _client_last_access.items()
        if now - last_access >= CLIENT_IDLE_TTL_SECONDS
    ]
    for key in expired_keys:
        cached = _client_cache.pop(key, None)
        _client_last_access.pop(key, None)
        _close_client_safely(cached)


def _resolve_pool_values_for_profile(
    *,
    graph_backend: str,
    client_profile: str,
    oracle_pool_min: Optional[int],
    oracle_pool_max: Optional[int],
    oracle_pool_increment: Optional[int],
    oracle_max_coroutines: Optional[int],
) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    if graph_backend != "oracle":
        return (
            oracle_pool_min,
            oracle_pool_max,
            oracle_pool_increment,
            oracle_max_coroutines,
        )
    if client_profile == CLIENT_PROFILE_BUILD_GRAPH:
        return (
            oracle_pool_min,
            oracle_pool_max,
            oracle_pool_increment,
            oracle_max_coroutines,
        )
    return (
        NON_BUILD_ORACLE_POOL_MIN,
        NON_BUILD_ORACLE_POOL_MAX,
        NON_BUILD_ORACLE_POOL_INCREMENT,
        NON_BUILD_ORACLE_MAX_COROUTINES,
    )


def _build_client_cache_key(
    *,
    backend: Optional[str],
    graph_backend: Optional[str],
    graphiti_embedding_model: Optional[str],
    project_id: Optional[str],
    enable_otel_tracing: Optional[bool],
    oracle_pool_min: Optional[int],
    oracle_pool_max: Optional[int],
    oracle_pool_increment: Optional[int],
    oracle_max_coroutines: Optional[int],
    client_profile: str,
) -> tuple[object, ...]:
    normalized_backend = str(backend or Config.ZEP_BACKEND or "").strip().lower()
    normalized_graph_backend = str(graph_backend or "").strip().lower()
    normalized_project_id = str(project_id or "").strip() or None
    normalized_embedding_model = str(graphiti_embedding_model or "").strip() or None
    normalized_tracing = bool(enable_otel_tracing) if enable_otel_tracing is not None else None
    normalized_pool_min, normalized_pool_max, normalized_pool_increment, normalized_max_coroutines = (
        _resolve_pool_values_for_profile(
            graph_backend=normalized_graph_backend,
            client_profile=client_profile,
            oracle_pool_min=oracle_pool_min,
            oracle_pool_max=oracle_pool_max,
            oracle_pool_increment=oracle_pool_increment,
            oracle_max_coroutines=oracle_max_coroutines,
        )
    )
    if normalized_graph_backend != "oracle":
        normalized_project_id = None
    return (
        normalized_backend,
        normalized_graph_backend,
        normalized_embedding_model,
        normalized_project_id,
        normalized_tracing,
        normalized_pool_min,
        normalized_pool_max,
        normalized_pool_increment,
        normalized_max_coroutines,
        client_profile,
    )


def get_or_create_zep_client(
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    graphdb_uri: Optional[str] = None,
    graphdb_user: Optional[str] = None,
    graphdb_password: Optional[str] = None,
    graph_backend: Optional[str] = None,
    graphiti_embedding_model: Optional[str] = None,
    project_id: Optional[str] = None,
    enable_otel_tracing: Optional[bool] = None,
    oracle_pool_min: Optional[int] = None,
    oracle_pool_max: Optional[int] = None,
    oracle_pool_increment: Optional[int] = None,
    oracle_max_coroutines: Optional[int] = None,
    client_profile: Optional[str] = None,
) -> ZepClientAdapter:
    normalized_profile = _normalize_client_profile(client_profile)
    cache_key = _build_client_cache_key(
        backend=backend,
        graph_backend=graph_backend,
        graphiti_embedding_model=graphiti_embedding_model,
        project_id=project_id,
        enable_otel_tracing=enable_otel_tracing,
        oracle_pool_min=oracle_pool_min,
        oracle_pool_max=oracle_pool_max,
        oracle_pool_increment=oracle_pool_increment,
        oracle_max_coroutines=oracle_max_coroutines,
        client_profile=normalized_profile,
    )
    now = time.monotonic()
    with _client_lock:
        _evict_idle_clients_locked(now)
        cached = _client_cache.get(cache_key)
        if cached is not None:
            _client_last_access[cache_key] = now
            return cached

    normalized_graph_backend = str(graph_backend or "").strip().lower()
    (
        resolved_pool_min,
        resolved_pool_max,
        resolved_pool_increment,
        resolved_max_coroutines,
    ) = _resolve_pool_values_for_profile(
        graph_backend=normalized_graph_backend,
        client_profile=normalized_profile,
        oracle_pool_min=oracle_pool_min,
        oracle_pool_max=oracle_pool_max,
        oracle_pool_increment=oracle_pool_increment,
        oracle_max_coroutines=oracle_max_coroutines,
    )
    try:
        created = create_zep_client(
            backend=backend,
            api_key=api_key,
            graphdb_uri=graphdb_uri,
            graphdb_user=graphdb_user,
            graphdb_password=graphdb_password,
            graph_backend=graph_backend,
            graphiti_embedding_model=graphiti_embedding_model,
            project_id=project_id,
            enable_otel_tracing=enable_otel_tracing,
            oracle_pool_min=resolved_pool_min,
            oracle_pool_max=resolved_pool_max,
            oracle_pool_increment=resolved_pool_increment,
            oracle_max_coroutines=resolved_max_coroutines,
        )
    except Exception:
        with _client_lock:
            stale = _client_cache.pop(cache_key, None)
            _client_last_access.pop(cache_key, None)
            _close_client_safely(stale)
        raise

    with _client_lock:
        now = time.monotonic()
        _evict_idle_clients_locked(now)
        existing = _client_cache.get(cache_key)
        if existing is not None:
            _client_last_access[cache_key] = now
            _close_client_safely(created)
            return existing
        _client_cache[cache_key] = created
        _client_last_access[cache_key] = now
    return created


def create_zep_client(
    backend: Optional[str] = None,
    api_key: Optional[str] = None,
    graphdb_uri: Optional[str] = None,
    graphdb_user: Optional[str] = None,
    graphdb_password: Optional[str] = None,
    graph_backend: Optional[str] = None,
    graphiti_embedding_model: Optional[str] = None,
    project_id: Optional[str] = None,
    enable_otel_tracing: Optional[bool] = None,
    oracle_pool_min: Optional[int] = None,
    oracle_pool_max: Optional[int] = None,
    oracle_pool_increment: Optional[int] = None,
    oracle_max_coroutines: Optional[int] = None,
) -> ZepClientAdapter:
    normalized_graph_backend = str(graph_backend or '').strip().lower()
    normalized_backend = str(backend or Config.ZEP_BACKEND or '').strip().lower()
    resolved_graphiti_db: Optional[str] = None

    if normalized_graph_backend in {'oracle', 'neo4j'}:
        normalized_backend = 'graphiti'
        resolved_graphiti_db = normalized_graph_backend
    elif normalized_graph_backend == 'zep_cloud':
        normalized_backend = 'zep_cloud'

    if normalized_backend == 'graphiti':
        return _create_graphiti_client(
            graphdb_uri,
            graphdb_user,
            graphdb_password,
            graphiti_db=resolved_graphiti_db,
            embedding_model=graphiti_embedding_model,
            project_id=project_id,
            enable_otel_tracing=enable_otel_tracing,
            oracle_pool_min=oracle_pool_min,
            oracle_pool_max=oracle_pool_max,
            oracle_pool_increment=oracle_pool_increment,
            oracle_max_coroutines=oracle_max_coroutines,
        )
    elif normalized_backend == 'zep_cloud':
        return _create_cloud_client(api_key)

    raise ValueError(
        f"Unsupported ZEP backend {backend}/{Config.ZEP_BACKEND}. "
        "Expected one of: zep_cloud, graphiti."
    )


def _create_cloud_client(api_key: Optional[str] = None) -> ZepClientAdapter:
    key = api_key or Config.ZEP_API_KEY
    if not key:
        raise ValueError(
            "ZEP_API_KEY is not configured. Using Zep Cloud requires setting ZEP_API_KEY environment variable."
        )

    logger.info("Creating Zep Cloud client")
    return ZepCloudClient(api_key=key)


def _create_graphiti_client(
    graphdb_uri: Optional[str] = None,
    graphdb_user: Optional[str] = None,
    graphdb_password: Optional[str] = None,
    dsn: Optional[str] = None,
    graphiti_db: Optional[str] = None,
    embedding_model: Optional[str] = None,
    project_id: Optional[str] = None,
    enable_otel_tracing: Optional[bool] = None,
    oracle_pool_min: Optional[int] = None,
    oracle_pool_max: Optional[int] = None,
    oracle_pool_increment: Optional[int] = None,
    oracle_max_coroutines: Optional[int] = None,
) -> ZepClientAdapter:
    """Graphiti Local Client"""

    graphiti_db = (graphiti_db or Config.GRAPHITI_DB or "neo4j").strip().lower()
    uri = graphdb_uri or Config.GRAPHDB_URI
    user = graphdb_user or Config.GRAPHDB_USER
    password = graphdb_password or Config.GRAPHDB_PASSWORD
    dsn = dsn or Config.GRAPHDB_DSN

    has_uri_config = all([uri, user, password])
    has_dsn_config = all([dsn, user, password])
    if graphiti_db not in {"neo4j", "oracle"}:
        raise ValueError(
            "GRAPHITI_DB is invalid. Expected one of: neo4j, oracle."
        )

    if graphiti_db == "oracle":
        if not has_dsn_config:
            raise ValueError(
                "Oracle Graphiti mode requires GRAPHDB_DSN, GRAPHDB_USER, and GRAPHDB_PASSWORD."
            )
        normalized_project_id = str(project_id or "").strip()
        if not normalized_project_id:
            raise ValueError(
                "Oracle Graphiti mode requires project_id. "
                "Pass project_id to create_zep_client(...) for project-scoped operations."
            )
        from graphiti_core.driver.oracle_pg_driver import OraclePGDriver
        pool_min = oracle_pool_min if oracle_pool_min is not None else Config.ORACLE_POOL_MIN
        pool_max = oracle_pool_max if oracle_pool_max is not None else Config.ORACLE_POOL_MAX
        pool_increment = (
            oracle_pool_increment
            if oracle_pool_increment is not None
            else Config.ORACLE_POOL_INCREMENT
        )
        max_coroutines = (
            oracle_max_coroutines
            if oracle_max_coroutines is not None
            else Config.ORACLE_MAX_COROUTINES
        )
        connect_kwargs: dict[str, int] = {}
        if isinstance(pool_min, int) and pool_min > 0:
            connect_kwargs["min"] = pool_min
        if isinstance(pool_max, int) and pool_max > 0:
            connect_kwargs["max"] = pool_max
        if isinstance(pool_increment, int) and pool_increment > 0:
            connect_kwargs["increment"] = pool_increment

        oracle_driver_kwargs: dict[str, object] = {
            "dsn": dsn,
            "user": user,
            "password": password,
            "graph_id": normalized_project_id,
            "log_queries": Config.ORACLE_LOG_QUERIES,
        }
        if isinstance(max_coroutines, int) and max_coroutines > 0:
            oracle_driver_kwargs["max_coroutines"] = max_coroutines
        if connect_kwargs:
            oracle_driver_kwargs["connect_kwargs"] = connect_kwargs
        logger.info(
            "Create Graphiti Oracle Client for project_id=%s (pool_min=%s pool_max=%s pool_increment=%s max_coroutines=%s)",
            normalized_project_id,
            connect_kwargs.get("min"),
            connect_kwargs.get("max"),
            connect_kwargs.get("increment"),
            oracle_driver_kwargs.get("max_coroutines"),
        )
        return GraphitiClient(
            graph_driver=OraclePGDriver(**oracle_driver_kwargs),
            embedding_model=embedding_model,
            enable_otel_tracing=enable_otel_tracing,
        )

    if not has_uri_config:
        raise ValueError(
            "Neo4j Graphiti mode requires GRAPHDB_URI, GRAPHDB_USER, and GRAPHDB_PASSWORD."
        )
    logger.info("Create Graphiti Neo4j Client: %s", uri)
    return GraphitiClient(
        graphdb_uri=uri,
        graphdb_user=user,
        graphdb_password=password,
        embedding_model=embedding_model,
        enable_otel_tracing=enable_otel_tracing,
    )

def get_zep_client() -> ZepClientAdapter:
    return get_or_create_zep_client(client_profile=CLIENT_PROFILE_NON_BUILD_GRAPH)


def reset_zep_client(cache_key: tuple[object, ...] | None = None):
    with _client_lock:
        if cache_key is not None:
            cached = _client_cache.pop(cache_key, None)
            _client_last_access.pop(cache_key, None)
            _close_client_safely(cached)
            logger.info("Zep client cache entry has been reset")
            return
        cache_items = list(_client_cache.items())
        _client_cache.clear()
        _client_last_access.clear()
    for _, client in cache_items:
        _close_client_safely(client)
    logger.info("All cached Zep client instances have been reset")
