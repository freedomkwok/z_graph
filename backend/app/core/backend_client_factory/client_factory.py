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

    graphiti_db = (Config.GRAPHITI_DB or "neo4j").strip().lower()
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
        from graphiti_core.driver.oracle_driver import OracleDriver
        logger.info("Create Graphiti Oracle Client: %s", dsn)
        return GraphitiClient(
            graph_driver=OracleDriver(
                dsn=dsn,
                user=user,
                password=password,
                use_rdf=Config.ORACLE_USE_RDF,
                rdf_network_owner=Config.ORACLE_RDF_NETWORK_OWNER,
                rdf_network_name=Config.ORACLE_RDF_NETWORK_NAME,
                rdf_graph_name=Config.ORACLE_RDF_GRAPH_NAME,
                rdf_tablespace=Config.ORACLE_RDF_TABLESPACE,
            )
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
