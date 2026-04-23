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
from typing import Optional

from app.core.config import Config
from app.core.backend_client_factory.schema import ZepClientAdapter
from app.core.backend_client_factory.zep.zep_client import ZepCloudClient
from app.core.backend_client_factory.graphiti.graphiti_client import GraphitiClient
logger = logging.getLogger('z_graph.zep_factory')


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
        logger.info("Create Graphiti Oracle Client: %s", dsn)
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

import threading

_client_instance: Optional[ZepClientAdapter] = None
_client_lock = threading.Lock()


def get_zep_client() -> ZepClientAdapter:
    global _client_instance
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                _client_instance = create_zep_client()
    return _client_instance


def reset_zep_client():
    global _client_instance
    with _client_lock:
        if _client_instance is not None:
            if hasattr(_client_instance, 'close'):
                try:
                    _client_instance.close()
                except Exception:
                    pass
            _client_instance = None
            logger.info("Global Zep client instance has been reset")
