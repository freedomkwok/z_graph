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
) -> ZepClientAdapter:
    if backend == 'graphiti':
        return _create_graphiti_client(graphdb_uri, graphdb_user, graphdb_password)
    elif backend == 'zep_cloud':
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
) -> ZepClientAdapter:
    """Graphiti Local Client"""
    
    uri = graphdb_uri or Config.GRAPHDB_URI
    user = graphdb_user or Config.GRAPHDB_USER
    password = graphdb_password or Config.GRAPHDB_PASSWORD
    dsn = dsn or Config.GRAPHDB_DSN

    has_uri_config = all([uri, user, password])
    has_dsn_config = all([dsn, user, password])
    if not (has_uri_config or has_dsn_config):
        raise ValueError(
            "GraphDB configuration is incomplete. Using Graphiti requires either "
            "(GRAPHDB_URI, GRAPHDB_USER, GRAPHDB_PASSWORD) or "
            "(GRAPHDB_DSN, GRAPHDB_USER, GRAPHDB_PASSWORD)."
        )

    logger.info(f"Create Graphiti Local Client: {uri}")
    if dsn:
        from graphiti_core.driver.oracle_driver import OracleDriver
        return GraphitiClient(
            graph_driver=OracleDriver(dsn=dsn, user=user, password=password)
        )
    else:
        return GraphitiClient(
            graphdb_uri=uri,
            graphdb_user=user,
            graphdb_password=password,
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
