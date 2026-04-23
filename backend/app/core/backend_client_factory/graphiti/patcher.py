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

import json
import functools
from typing import Any, Dict
import logging
from graphiti_core.utils import bulk_utils

logger = logging.getLogger('z_graph.graphiti_patch')
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
            for i, n in enumerate(entity_nodes[:3]):
                logger.info("entity_node[%s] type=%s uuid=%s", i, type(n), getattr(n, "uuid", None))
            for i, e in enumerate(episodic_nodes[:3]):
                logger.info("episodic_node[%s] type=%s uuid=%s", i, type(e), getattr(e, "uuid", None))
                
            # Sanitize entity_nodes attributes
            for node in entity_nodes:
                if hasattr(node, 'attributes') and node.attributes:
                    node.attributes = sanitize_attributes(node.attributes)
                if hasattr(node, 'name_embedding') and node.name_embedding:
                    node.name_embedding = None #name_embedding

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
