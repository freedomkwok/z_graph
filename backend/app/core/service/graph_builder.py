import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Optional

from zep_cloud import EntityEdgeSourceTarget, EpisodeData
from zep_cloud.client import Zep

from app.core.config import Config
from app.core.managers.task_manager import TaskManager
from app.core.schemas.task import TaskStatus
from app.core.schemas.zep_operation import GraphInfo
from app.core.service.zep_service import fetch_all_edges, fetch_all_nodes
from app.core.utils.text_processor import TextProcessor
from pydantic import Field
from zep_cloud.external_clients.ontology import EdgeModel, EntityModel, EntityText


class GraphBuilderService:
    """
    Graph build service.
    Calls the Zep API to build the knowledge graph.
    """

    def __init__(self, api_key: str | None = None, client: Any | None = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY Not Configured")

        self.client = self._normalize_client(client or Zep(api_key=self.api_key))
        self._validate_required_graph_api(self.client)
        self.task_manager = TaskManager()

    @staticmethod
    def _normalize_client(client: Any) -> Any:
        """Normalize cloud clients to a shape exposing `.graph.*` APIs."""
        if hasattr(client, "graph"):
            return client

        inner_client = getattr(client, "client", None)
        if inner_client is not None and hasattr(inner_client, "graph"):
            return inner_client

        raise TypeError(
            "Unsupported Zep client: expected object with `graph` or `client.graph` APIs."
        )

    @staticmethod
    def _validate_required_graph_api(client: Any) -> None:
        """Ensure the client has all graph APIs needed by main build/delete routes."""
        graph = getattr(client, "graph", None)
        missing: list[str] = []

        for method_name in ("create", "update", "set_ontology", "add_batch", "delete"):
            if not callable(getattr(graph, method_name, None)):
                missing.append(f"graph.{method_name}")

        if not callable(getattr(getattr(graph, "episode", None), "get", None)):
            missing.append("graph.episode.get")

        if not callable(getattr(getattr(graph, "node", None), "get_by_graph_id", None)):
            missing.append("graph.node.get_by_graph_id")

        if not callable(getattr(getattr(graph, "edge", None), "get_by_graph_id", None)):
            missing.append("graph.edge.get_by_graph_id")

        if missing:
            raise TypeError(
                "Zep client is missing required APIs for GraphBuilderService: "
                + ", ".join(missing)
            )

    def build_graph_async(
        self,
        text: str,
        ontology: dict[str, Any],
        graph_name: str = "imp Graph",
        project_id: str | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3,
    ) -> str:
        # Create task
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            },
        )

        thread = threading.Thread(
            target=self._build_graph,
            args=(task_id, text, ontology, graph_name, project_id, chunk_size, chunk_overlap, batch_size),
        )
        thread.daemon = True
        thread.start()

        return task_id

    def _build_graph(
        self,
        task_id: str,
        text: str,
        ontology: dict[str, Any],
        graph_name: str,
        project_id: str | None,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
    ):
        try:
            self.task_manager.update_task(
                task_id, status=TaskStatus.PROCESSING, progress=5, message="Start building graph..."
            )

            graph_id, project_workspace_id = self.create_graph(graph_name, project_id=project_id)
            self.task_manager.update_task(
                task_id, progress=10, message=f"Graph created: {graph_id}"
            )

            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(task_id, progress=15, message="Ontology set")

            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id, progress=20, message=f"Splitted into {total_chunks} chunks"
            )

            episode_uuids = self.add_text_batches(
                graph_id,
                chunks,
                batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # 20-60%
                    message=msg,
                ),
            )

            self.task_manager.update_task(
                task_id, progress=60, message="waiting for Zep to process data"
            )

            self._wait_for_episodes(
                episode_uuids,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=60 + int(prog * 0.3),  # 60-90%
                    message=msg,
                ),
            )

            self.task_manager.update_task(task_id, progress=90, message="Getting graph info")

            graph_info = self._get_graph_info(graph_id)

            self.task_manager.complete_task(
                task_id,
                {
                    "graph_id": graph_id,
                    "project_workspace_id": project_workspace_id,
                    "graph_info": graph_info.to_dict(),
                    "chunks_processed": total_chunks,
                },
            )

        except Exception as e:
            import traceback

            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)

    @staticmethod
    def _extract_project_workspace_id(graph_obj: Any) -> str | None:
        workspace_id = getattr(graph_obj, "project_uuid", None)
        if workspace_id is None:
            return None
        normalized_workspace_id = str(workspace_id).strip()
        return normalized_workspace_id or None

    def create_graph(self, name: str, project_id: str | None = None) -> tuple[str, str | None]:
        """Create a Zep graph (public API)."""
        normalized_project_id = str(project_id or "").strip()
        graph_id = normalized_project_id or f"imp_{uuid.uuid4().hex[:16]}"

        if normalized_project_id:
            try:
                created_graph = self.client.graph.create(
                    graph_id=graph_id, name=name, description="Zep Graph"
                )
                return graph_id, self._extract_project_workspace_id(created_graph)
            except Exception as error:
                status_code = getattr(error, "status_code", None)
                error_text = str(error).lower()
                already_exists = (
                    status_code == 409
                    or "already exists" in error_text
                    or "already_exist" in error_text
                    or "conflict" in error_text
                )
                if not already_exists:
                    raise

                updated_graph = self.client.graph.update(
                    graph_id=graph_id, name=name, description="Zep Graph"
                )
                return graph_id, self._extract_project_workspace_id(updated_graph)

        created_graph = self.client.graph.create(graph_id=graph_id, name=name, description="Zep Graph")

        return graph_id, self._extract_project_workspace_id(created_graph)

    def set_ontology(self, graph_id: str, ontology: dict[str, Any]):
        """Apply ontology to the graph (public API)."""
        import warnings

        # Suppress Pydantic v2 warnings about Field(default=None); Zep SDK requires this pattern.
        warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

        # Zep reserved names cannot be used as attribute names
        RESERVED_NAMES = {"uuid", "name", "group_id", "name_embedding", "summary", "created_at"}

        def safe_attr_name(attr_name: str) -> str:
            """Map reserved names to safe attribute names."""
            if attr_name.lower() in RESERVED_NAMES:
                return f"entity_{attr_name}"
            return attr_name

        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")

            attrs = {"__doc__": description}
            annotations = {}

            for attr_def in entity_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # safe name
                attr_desc = attr_def.get("description", attr_name)
                # Zep API requires Field(description=...)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]  # type hint

            attrs["__annotations__"] = annotations

            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class

        edge_definitions = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")

            attrs = {"__doc__": description}
            annotations = {}

            for attr_def in edge_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # safe name
                attr_desc = attr_def.get("description", attr_name)
                # Zep API requires Field(description=...)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]  # edge attrs use str

            attrs["__annotations__"] = annotations

            class_name = "".join(word.capitalize() for word in name.split("_"))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description

            source_targets = []
            for st in edge_def.get("source_targets", []):
                source_targets.append(
                    EntityEdgeSourceTarget(
                        source=st.get("source", "Entity"), target=st.get("target", "Entity")
                    )
                )

            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)

        # Call Zep to set ontology
        if entity_types or edge_definitions:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=entity_types if entity_types else None,
                edges=edge_definitions if edge_definitions else None,
            )

    def add_text_batches(
        self,
        graph_id: str,
        chunks: list[str],
        batch_size: int = 3,
        progress_callback: Callable | None = None,
    ) -> list[str]:
        """Add text in batches; returns episode UUIDs."""
        episode_uuids = []
        total_chunks = len(chunks)

        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size

            if progress_callback:
                progress = (i + len(batch_chunks)) / total_chunks
                progress_callback(
                    f"sending {batch_num}/{total_batches} with ({len(batch_chunks)})", progress
                )

            episodes = [EpisodeData(data=chunk, type="text") for chunk in batch_chunks]

            try:
                batch_result = self.client.graph.add_batch(graph_id=graph_id, episodes=episodes)

                # Collect returned episode UUIDs
                if batch_result and isinstance(batch_result, list):
                    for ep in batch_result:
                        ep_uuid = getattr(ep, "uuid_", None) or getattr(ep, "uuid", None)
                        if ep_uuid:
                            episode_uuids.append(ep_uuid)

                time.sleep(1)

            except Exception as e:
                if progress_callback:
                    progress_callback(f"batch {batch_num} failed: {str(e)}", 0)
                raise

        return episode_uuids

    def _wait_for_episodes(
        self,
        episode_uuids: list[str],
        progress_callback: Callable | None = None,
        timeout: int = 600,
    ):
        if not episode_uuids:
            if progress_callback:
                progress_callback("No need to wait (no episode)", 1.0)
            return

        start_time = time.time()
        pending_episodes = set(episode_uuids)
        completed_count = 0
        total_episodes = len(episode_uuids)

        if progress_callback:
            progress_callback(f"Waiting for {total_episodes} text chunks to be processed...", 0)

        while pending_episodes:
            if time.time() - start_time > timeout:
                if progress_callback:
                    progress_callback(
                        f"Some text chunks timed out, {completed_count}/{total_episodes} completed",
                        completed_count / total_episodes,
                    )
                break

            # Poll each episode
            for ep_uuid in list(pending_episodes):
                try:
                    episode = self.client.graph.episode.get(uuid_=ep_uuid)
                    is_processed = getattr(episode, "processed", False)

                    if is_processed:
                        pending_episodes.remove(ep_uuid)
                        completed_count += 1

                except Exception:
                    # Ignore single-episode query errors
                    pass

            elapsed = int(time.time() - start_time)
            if progress_callback:
                progress_callback(
                    f"Zep processing {completed_count}/{total_episodes} completed, {len(pending_episodes)} pending ({elapsed} seconds)",
                    completed_count / total_episodes if total_episodes > 0 else 0,
                )

            if pending_episodes:
                time.sleep(3)  # poll every 3 seconds

        if progress_callback:
            progress_callback(f"Processing completed: {completed_count}/{total_episodes}", 1.0)

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """Load graph summary (counts and entity types)."""
        # Nodes (paged)
        nodes = fetch_all_nodes(self.client, graph_id)

        # Edges (paged)
        edges = fetch_all_edges(self.client, graph_id)

        # Entity type labels
        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types),
        )

    def get_graph_data(self, graph_id: str) -> dict[str, Any]:
        """
        Return full graph payload with rich node/edge details.

        Args:
            graph_id: Graph ID

        Returns:
            Dict with nodes and edges, including temporal fields and attributes.
        """
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

        # UUID -> name for edge endpoints
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""

        nodes_data = []
        for node in nodes:
            # created_at
            created_at = getattr(node, "created_at", None)
            if created_at:
                created_at = str(created_at)

            nodes_data.append(
                {
                    "uuid": node.uuid_,
                    "name": node.name,
                    "labels": node.labels or [],
                    "summary": node.summary or "",
                    "attributes": node.attributes or {},
                    "created_at": created_at,
                }
            )

        edges_data = []
        for edge in edges:
            # Temporal fields
            created_at = getattr(edge, "created_at", None)
            valid_at = getattr(edge, "valid_at", None)
            invalid_at = getattr(edge, "invalid_at", None)
            expired_at = getattr(edge, "expired_at", None)

            # Episodes
            episodes = getattr(edge, "episodes", None) or getattr(edge, "episode_ids", None)
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]

            # fact_type
            fact_type = getattr(edge, "fact_type", None) or edge.name or ""

            edges_data.append(
                {
                    "uuid": edge.uuid_,
                    "name": edge.name or "",
                    "fact": edge.fact or "",
                    "fact_type": fact_type,
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "source_node_name": node_map.get(edge.source_node_uuid, ""),
                    "target_node_name": node_map.get(edge.target_node_uuid, ""),
                    "attributes": edge.attributes or {},
                    "created_at": str(created_at) if created_at else None,
                    "valid_at": str(valid_at) if valid_at else None,
                    "invalid_at": str(invalid_at) if invalid_at else None,
                    "expired_at": str(expired_at) if expired_at else None,
                    "episodes": episodes or [],
                }
            )

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str):
        """Delete a graph."""
        self.client.graph.delete(graph_id=graph_id)
