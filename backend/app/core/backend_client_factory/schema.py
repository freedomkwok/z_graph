from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

@dataclass
class GraphNode:
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    created_at: Optional[str] = None


@dataclass
class GraphEdge:
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    attributes: Dict[str, Any]
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    episodes: List[str] = field(default_factory=list)
    fact_type: Optional[str] = None

@dataclass
class SearchResult:
    nodes: List[GraphNode]
    edges: List[GraphEdge]


@dataclass
class EpisodeStatus:
    uuid: str
    processed: bool


class ZepClientAdapter(ABC):
    @abstractmethod
    def create_graph(self, graph_id: str, name: str, description: str) -> None:
        ...

    @abstractmethod
    def delete_graph(self, graph_id: str) -> None:
        ...

    @abstractmethod
    def set_ontology(
        self,
        graph_ids: List[str],
        entities: Optional[Dict[str, Any]] = None,
        edges: Optional[Dict[str, Any]] = None
    ) -> None:
        ...

    # ==================== Episode operations ====================

    @abstractmethod
    def add_episode(self, graph_id: str, data: str, episode_type: str = "text") -> str:
        ...

    @abstractmethod
    def add_episode_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, Any]]
    ) -> List[str]:
        ...

    @abstractmethod
    def get_episode_status(self, episode_uuid: str) -> EpisodeStatus:
        ...

    def wait_for_episode(self, episode_uuid: str, timeout: int = 300) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.get_episode_status(episode_uuid)
            if status.processed:
                return True
            time.sleep(3)
        return False

    # ==================== Node operations ====================

    @abstractmethod
    def get_all_nodes(self, graph_id: str) -> List[GraphNode]:
        ...

    @abstractmethod
    def get_node(self, node_uuid: str) -> Optional[GraphNode]:
        ...

    @abstractmethod
    def get_node_edges(self, node_uuid: str) -> List[GraphEdge]:
        ...

    # ==================== Edge operations ====================

    @abstractmethod
    def get_all_edges(self, graph_id: str) -> List[GraphEdge]:
        ...

    # ==================== Search operations ====================

    @abstractmethod
    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        reranker: str = "cross_encoder"
    ) -> SearchResult:
        ...
