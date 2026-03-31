from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ProjectStatus(str, Enum):
    CREATED = "created"
    ONTOLOGY_GENERATED = "ontology_generated"
    GRAPH_BUILDING = "graph_building"
    GRAPH_COMPLETED = "graph_completed"
    FAILED = "failed" 

@dataclass
class Project:
    project_id: str
    name: str
    status: ProjectStatus
    created_at: str
    updated_at: str
    
    files: list[dict[str, str]] = field(default_factory=list)  # [{filename, path, size}]
    total_text_length: int = 0
    
    ontology: dict[str, Any] | None = None
    analysis_summary: str | None = None
    
    zep_graph_id: str | None = None
    project_workspace_id: str | None = None
    zep_graph_address: str | None = None
    graph_build_task_id: str | None = None
    
    context_requirement: str | None = None
    prompt_label: str = "Production"
    minimum_nodes: int = 10
    minimum_edges: int = 10
    chunk_size: int = 500
    chunk_overlap: int = 50
    
    error: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status.value if isinstance(self.status, ProjectStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": self.files,
            "total_text_length": self.total_text_length,
            "ontology": self.ontology,
            "analysis_summary": self.analysis_summary,
            "zep_graph_id": self.zep_graph_id,
            "project_workspace_id": self.project_workspace_id,
            "zep_graph_address": self.zep_graph_address,
            "graph_build_task_id": self.graph_build_task_id,
            "context_requirement": self.context_requirement,
            "prompt_label": self.prompt_label,
            "minimum_nodes": self.minimum_nodes,
            "minimum_edges": self.minimum_edges,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "error": self.error
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Project':
        status = data.get('status', 'created')
        if isinstance(status, str):
            status = ProjectStatus(status)
        
        zep_graph_id = data.get("zep_graph_id") or data.get("graph_id")
        project_workspace_id = data.get("project_workspace_id")

        return cls(
            project_id=data['project_id'],
            name=data.get('name', 'Unnamed Project'),
            status=status,
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
            files=data.get('files', []),
            total_text_length=data.get('total_text_length', 0),
            ontology=data.get('ontology'),
            analysis_summary=data.get('analysis_summary'),
            zep_graph_id=zep_graph_id,
            project_workspace_id=project_workspace_id,
            zep_graph_address=data.get("zep_graph_address"),
            graph_build_task_id=data.get('graph_build_task_id'),
            context_requirement=data.get('context_requirement'),
            prompt_label=data.get("prompt_label", "Production"),
            minimum_nodes=_as_int(data.get("minimum_nodes", 10), 10),
            minimum_edges=_as_int(data.get("minimum_edges", 10), 10),
            chunk_size=_as_int(data.get('chunk_size', 500), 500),
            chunk_overlap=_as_int(data.get('chunk_overlap', 50), 50),
            error=data.get('error')
        )
