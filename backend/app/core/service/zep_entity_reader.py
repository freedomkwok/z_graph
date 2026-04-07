"""
Zep entity reader and filter.
Loads nodes from a Zep graph and keeps nodes whose labels match defined entity types.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from app.core.backend_client_factory.client_factory import create_zep_client
from app.core.backend_client_factory.schema import ZepClientAdapter
from app.core.config import Config
from app.core.schemas.zep_operation import EntityNode, FilteredEntities
from app.core.service.retrieval import fetch_all_edges, fetch_all_nodes
from app.core.utils.logger import get_logger
from app.core.utils.retry import call_with_retry

logger = get_logger('z_graph.zep_entity_reader')
T = TypeVar('T')

class ZepEntityReader:
    """
    Read Zep graphs and filter to defined entity types.

    Steps: load all nodes, keep nodes with custom labels (not only Entity),
    optionally attach related edges and neighbor nodes.
    """
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        self.client: ZepClientAdapter = create_zep_client(
            backend=Config.ZEP_BACKEND,
            api_key=self.api_key,
        )
    
    def _call_with_retry(
        self, 
        func: Callable[[], T], 
        operation_name: str,
        max_retries: int = 3,
        initial_delay: float = 2.0
    ) -> T:
        """
        Call Zep with retries and exponential backoff.

        Args:
            func: Zero-arg callable
            operation_name: Label for logs
            max_retries: Max attempts
            initial_delay: First backoff in seconds

        Returns:
            Result of func()
        """
        try:
            return call_with_retry(
                func=func,
                operation_name=f"Zep {operation_name}",
                logger=logger,
                max_retries=max_retries,
                initial_delay=initial_delay,
            )
        except Exception as e:
            logger.error(f"Zep {operation_name} failed after {max_retries} attempts: {str(e)}")
            raise
    
    def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
        logger.info(f"Retrieving GRAPH[{graph_id}] Nodes")

        nodes = fetch_all_nodes(self.client, graph_id)

        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
            })

        logger.info(f"Total: {len(nodes_data)} Nodes")
        return nodes_data

    def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
        logger.info(f"Retrieving GRAPH[{graph_id}] Edges")

        edges = fetch_all_edges(self.client, graph_id)

        edges_data = []
        for edge in edges:
            edges_data.append({
                "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                "name": edge.name or "",
                "fact": edge.fact or "",
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "attributes": edge.attributes or {},
            })

        logger.info(f"Total: {len(edges_data)} Edges")
        return edges_data
    
    def get_node_edges(self, node_uuid: str) -> list[dict[str, Any]]:
        try:
            edges = self._call_with_retry(
                func=lambda: self.client.get_node_edges(node_uuid),
                operation_name=f"Retrieve NodeEdges(node={node_uuid[:8]})"
            )
            
            edges_data = []
            for edge in edges:
                edges_data.append({
                    "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                    "name": edge.name or "",
                    "fact": edge.fact or "",
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "attributes": edge.attributes or {},
                })
            
            return edges_data
        except Exception as e:
            logger.warning(f"Retrieve Node[{node_uuid}] Edges Failed: {str(e)}")
            return []
    
    def filter_defined_entities(
        self, 
        graph_id: str,
        defined_entity_types: list[str] | None = None,
        enrich_with_edges: bool = True
    ) -> FilteredEntities:
        """
        Keep nodes whose labels indicate a custom entity type.

        Rules:
        - Skip nodes whose only custom label is the default Entity bucket.
        - Keep nodes with any label outside Entity/Node (custom ontology type).

        Args:
            graph_id: Graph id
            defined_entity_types: If set, only these label names are kept
            enrich_with_edges: Load related edges and neighbors

        Returns:
            FilteredEntities instance
        """
        logger.info(f"Begin to filter {graph_id} Entities...")
        
        # All nodes
        all_nodes = self.get_all_nodes(graph_id)
        total_count = len(all_nodes)
        
        # All edges for neighborhood expansion
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        
        # uuid -> node row
        node_map = {n["uuid"]: n for n in all_nodes}
        
        # Filter
        filtered_entities = []
        entity_types_found = set()
        
        for node in all_nodes:
            labels = node.get("labels", [])
            
            # Require at least one non-default label
            custom_labels = [l for l in labels if l not in ["Entity", "Node"]]
            
            if not custom_labels:
                # Only default labels; skip
                continue
            
            # Optional whitelist
            if defined_entity_types:
                matching_labels = [l for l in custom_labels if l in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]
            
            entity_types_found.add(entity_type)
            
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node["summary"],
                attributes=node["attributes"],
            )
            
            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()
                
                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])
                
                entity.related_edges = related_edges
                
                related_nodes = []
                for related_uuid in related_node_uuids:
                    if related_uuid in node_map:
                        related_node = node_map[related_uuid]
                        related_nodes.append({
                            "uuid": related_node["uuid"],
                            "name": related_node["name"],
                            "labels": related_node["labels"],
                            "summary": related_node.get("summary", ""),
                        })
                
                entity.related_nodes = related_nodes
            
            filtered_entities.append(entity)
        
        logger.info(f"Filter finished: Total Entity Count {total_count}, filtered count {len(filtered_entities)}, "
                   f"Final Entity Count: {entity_types_found}")
        
        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=total_count,
            filtered_count=len(filtered_entities),
        )
    
    def get_entity_with_context(
        self, 
        graph_id: str, 
        entity_uuid: str
    ) -> EntityNode | None:
        """
        One entity with neighborhood (edges and neighbors), with retries.

        Args:
            graph_id: Graph id
            entity_uuid: Entity node UUID

        Returns:
            EntityNode or None
        """
        try:
            # Node fetch with retry
            node = self._call_with_retry(
                func=lambda: self.client.get_node(entity_uuid),
                operation_name=f"entity_detail(uuid={entity_uuid[:8]}...)"
            )
            
            if not node:
                return None
            
            edges = self.get_node_edges(entity_uuid)
            
            all_nodes = self.get_all_nodes(graph_id)
            node_map = {n["uuid"]: n for n in all_nodes}
            
            related_edges = []
            related_node_uuids = set()
            
            for edge in edges:
                if edge["source_node_uuid"] == entity_uuid:
                    related_edges.append({
                        "direction": "outgoing",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "target_node_uuid": edge["target_node_uuid"],
                    })
                    related_node_uuids.add(edge["target_node_uuid"])
                else:
                    related_edges.append({
                        "direction": "incoming",
                        "edge_name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": edge["source_node_uuid"],
                    })
                    related_node_uuids.add(edge["source_node_uuid"])
            
            related_nodes = []
            for related_uuid in related_node_uuids:
                if related_uuid in node_map:
                    related_node = node_map[related_uuid]
                    related_nodes.append({
                        "uuid": related_node["uuid"],
                        "name": related_node["name"],
                        "labels": related_node["labels"],
                        "summary": related_node.get("summary", ""),
                    })
            
            return EntityNode(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {},
                related_edges=related_edges,
                related_nodes=related_nodes,
            )
            
        except Exception as e:
            logger.error(f"Failed to get entity {entity_uuid}: {str(e)}")
            return None
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str,
        enrich_with_edges: bool = True
    ) -> list[EntityNode]:
        """
        All entities of a given label.

        Args:
            graph_id: Graph id
            entity_type: Label name (e.g. Student, PublicFigure)
            enrich_with_edges: Attach neighborhood

        Returns:
            List of EntityNode
        """
        result = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges
        )
        return result.entities


