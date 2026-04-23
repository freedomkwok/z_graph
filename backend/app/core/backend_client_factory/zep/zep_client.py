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

from typing import Any, Dict, List, Optional

from zep_cloud.client import Zep
from zep_cloud import EpisodeData

from app.core.backend_client_factory.schema import (
    ZepClientAdapter,
    GraphNode,
    GraphEdge,
    SearchResult,
    EpisodeStatus,
)

class ZepCloudClient(ZepClientAdapter):
    _DEFAULT_PAGE_SIZE = 100

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("ZEP_API_KEY is not configured")
        self.client = Zep(api_key=api_key)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        self.client.graph.create(
            graph_id=graph_id,
            name=name,
            description=description
        )

    def delete_graph(self, graph_id: str) -> None:
        self.client.graph.delete(graph_id=graph_id)

    def set_ontology(
        self,
        graph_ids: List[str],
        entities: Optional[Dict[str, Any]] = None,
        edges: Optional[Dict[str, Any]] = None
    ) -> None:
        if entities or edges:
            self.client.graph.set_ontology(
                graph_ids=graph_ids,
                entities=entities if entities else None,
                edges=edges if edges else None,
            )

    def add_episode(self, graph_id: str, data: str, episode_type: str = "text") -> str:
        result = self.client.graph.add(
            graph_id=graph_id,
            type=episode_type,
            data=data
        )
        return getattr(result, 'uuid_', None) or getattr(result, 'uuid', '') or ''

    def add_episode_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, Any]]
    ) -> List[str]:
        episode_data_list = [
            EpisodeData(data=ep.get("data", ""), type=ep.get("type", "text"))
            for ep in episodes
        ]

        batch_result = self.client.graph.add_batch(
            graph_id=graph_id,
            episodes=episode_data_list
        )

        uuids = []
        if batch_result and isinstance(batch_result, list):
            for ep in batch_result:
                ep_uuid = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                if ep_uuid:
                    uuids.append(ep_uuid)
        return uuids

    def get_episode_status(self, episode_uuid: str) -> EpisodeStatus:
        episode = self.client.graph.episode.get(uuid_=episode_uuid)
        return EpisodeStatus(
            uuid=episode_uuid,
            processed=getattr(episode, 'processed', False)
        )

    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        all_nodes: List[GraphNode] = []
        cursor: Optional[str] = None

        while True:
            kwargs: Dict[str, Any] = {"limit": self._DEFAULT_PAGE_SIZE}
            if cursor is not None:
                kwargs["uuid_cursor"] = cursor

            batch = self.client.graph.node.get_by_graph_id(graph_id=graph_id, **kwargs)
            if not batch:
                break

            all_nodes.extend(self._convert_node(node) for node in batch)
            if len(batch) < self._DEFAULT_PAGE_SIZE:
                break

            cursor = getattr(batch[-1], "uuid_", None) or getattr(batch[-1], "uuid", None)
            if not cursor:
                break

        return all_nodes

    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        try:
            node = self.client.graph.node.get(uuid_=node_uuid)
            return self._convert_node(node) if node else None
        except Exception:
            return None

    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        try:
            edges = self.client.graph.node.get_entity_edges(node_uuid=node_uuid)
            return [self._convert_edge(edge) for edge in edges]
        except Exception:
            return []

    # ==================== Edge operations ====================

    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        all_edges: List[GraphEdge] = []
        cursor: Optional[str] = None

        while True:
            kwargs: Dict[str, Any] = {"limit": self._DEFAULT_PAGE_SIZE}
            if cursor is not None:
                kwargs["uuid_cursor"] = cursor

            batch = self.client.graph.edge.get_by_graph_id(graph_id=graph_id, **kwargs)
            if not batch:
                break

            all_edges.extend(self._convert_edge(edge) for edge in batch)
            if len(batch) < self._DEFAULT_PAGE_SIZE:
                break

            cursor = getattr(batch[-1], "uuid_", None) or getattr(batch[-1], "uuid", None)
            if not cursor:
                break

        return all_edges

    # ==================== Search operations ====================

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: str = "cross_encoder"
    ) -> SearchResult:
        search_result = self.client.graph.search(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope,
            reranker=reranker
        )

        nodes = []
        edges = []

        # Handle nodes
        if hasattr(search_result, 'nodes') and search_result.nodes:
            nodes = [self._convert_node(n) for n in search_result.nodes]

        # Handle edges
        if hasattr(search_result, 'edges') and search_result.edges:
            edges = [self._convert_edge(e) for e in search_result.edges]

        return SearchResult(nodes=nodes, edges=edges)

    def _convert_node(self, node: Any) -> GraphNode:
        created_at = getattr(node, 'created_at', None)
        return GraphNode(
            uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
            name=node.name or '',
            labels=node.labels or [],
            summary=node.summary or '',
            attributes=node.attributes or {},
            created_at=str(created_at) if created_at else None
        )

    def _convert_edge(self, edge: Any) -> GraphEdge:
        created_at = getattr(edge, 'created_at', None)
        valid_at = getattr(edge, 'valid_at', None)
        invalid_at = getattr(edge, 'invalid_at', None)
        expired_at = getattr(edge, 'expired_at', None)

        episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None)
        if episodes and not isinstance(episodes, list):
            episodes = [str(episodes)]
        elif episodes:
            episodes = [str(e) for e in episodes]
        else:
            episodes = []

        return GraphEdge(
            uuid=getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
            name=edge.name or '',
            fact=edge.fact or '',
            source_node_uuid=edge.source_node_uuid,
            target_node_uuid=edge.target_node_uuid,
            attributes=edge.attributes or {},
            created_at=str(created_at) if created_at else None,
            valid_at=str(valid_at) if valid_at else None,
            invalid_at=str(invalid_at) if invalid_at else None,
            expired_at=str(expired_at) if expired_at else None,
            episodes=episodes,
            fact_type=getattr(edge, 'fact_type', None) or edge.name or ''
        )
