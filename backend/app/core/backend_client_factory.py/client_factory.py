import logging
from functools import lru_cache
from typing import Optional

from app.core.config import Config
from app.core.graphiti.schema import ZepClientAdapter
from app.core.graphiti.zep_cloud_impl import ZepCloudClient
from app.core.graphiti.zep_graphiti_impl import GraphitiClient

logger = logging.getLogger('zep_graph.zep_factory')


def create_zep_client(
    core: Optional[str] = None,
    api_key: Optional[str] = None,
    graphdb_uri: Optional[str] = None,
    graphdb_user: Optional[str] = None,
    graphdb_password: Optional[str] = None,
) -> ZepClientAdapter:
    core = core or Config.ZEP_CORE

    if core == 'graphiti':
        return _create_graphiti_client(graphdb_uri, graphdb_user, graphdb_password)
    else:
        return _create_cloud_client(api_key)


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
) -> ZepClientAdapter:
    """Graphiti Local Client"""
    
    uri = graphdb_uri or Config.GRAPHDB_URI
    user = graphdb_user or Config.GRAPHDB_USER
    password = graphdb_password or Config.GRAPHDB_PASSWORD

    if not all([uri, user, password]):
        raise ValueError(
            "GraphDB configuration is incomplete. Using Graphiti requires setting GRAPHDB_URI, GRAPHDB_USER, GRAPHDB_PASSWORD."
        )

    logger.info(f"Create Graphiti Local Client: {uri}")
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
