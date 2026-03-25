import json
import functools
from typing import Any, Dict
import logging
from graphiti_core.utils import bulk_utils

logger = logging.getLogger('zep_graph.graphiti_patch')
_patch_applied = False

def sanitize_for_graphdb(value: Any, path: str = "") -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize dict attribute {path}: {e}")
            return str(value)

    if isinstance(value, (list, tuple)):
        is_simple = all(isinstance(v, (str, int, float, bool, type(None))) for v in value)
        if is_simple:
            return list(value)

        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize list attribute {path}: {e}")
            return str(value)

    return str(value)


def sanitize_attributes(attrs: Dict[str, Any]) -> Dict[str, Any]:
    if not attrs:
        return {}

    sanitized = {}
    for key, value in attrs.items():
        sanitized[key] = sanitize_for_graphdb(value, path=key)
    return sanitized


def apply_patch() -> bool:
    global _patch_applied

    if _patch_applied:
        logger.debug("Graphiti patch has been applied, skipping")
        return True

    try:
        original_add_nodes_and_edges_bulk_tx = bulk_utils.add_nodes_and_edges_bulk_tx

        @functools.wraps(original_add_nodes_and_edges_bulk_tx)
        async def patched_add_nodes_and_edges_bulk_tx(
            tx,  # GraphDriverSession (from session.execute_write)
            episodic_nodes,
            episodic_edges,
            entity_nodes,
            entity_edges,
            embedder,
            driver,
        ):
            """
            Patched version: sanitize node/edge attributes before Neo4j write

            signature with graphiti-core 0.25.0's add_nodes_and_edges_bulk_tx:
            (tx, episodic_nodes, episodic_edges, entity_nodes, entity_edges, embedder, driver)
            """
            # Sanitize entity_nodes attributes
            for node in entity_nodes:
                if hasattr(node, 'attributes') and node.attributes:
                    node.attributes = sanitize_attributes(node.attributes)
                if hasattr(node, 'name_embedding') and node.name_embedding:
                    node.name_embedding = "" #name_embedding

            # Sanitize entity_edges attributes
            for edge in entity_edges:
                if hasattr(edge, 'attributes') and edge.attributes:
                    edge.attributes = sanitize_attributes(edge.attributes)

            return await original_add_nodes_and_edges_bulk_tx(
                tx,
                episodic_nodes,
                episodic_edges,
                entity_nodes,
                entity_edges,
                embedder,
                driver,
            )

        #patch
        bulk_utils.add_nodes_and_edges_bulk_tx = patched_add_nodes_and_edges_bulk_tx

        _patch_applied = True
        logger.info("Graphiti bulk_utils patch applied successfully")
        return True

    except ImportError as e:
        logger.warning(f"Failed to import graphiti_core.utils.bulk_utils: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to apply Graphiti patch: {e}")
        return False
