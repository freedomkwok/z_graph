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

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_chunk_mode(value: Any, default: str = "fixed") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"fixed", "semantic", "hybrid", "llama_index"}:
        return normalized
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int):
        return value != 0
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
    graph_backend: str | None = None
    graphiti_embedding_model: str | None = None
    enable_otel_tracing: bool | None = None
    enable_oracle_runtime_overrides: bool = True
    oracle_pool_min: int | None = None
    oracle_pool_max: int | None = None
    oracle_pool_increment: int | None = None
    oracle_max_coroutines: int | None = None
    project_workspace_id: str | None = None
    zep_graph_address: str | None = None
    graph_build_task_id: str | None = None
    has_built_graph: bool = False
    graph_resume_candidate: dict[str, Any] | None = None
    refresh_data_while_build: bool = True
    
    context_requirement: str | None = None
    prompt_label: str | None = None
    prompt_label_id: int | None = None
    minimum_nodes: int = 10
    minimum_edges: int = 10
    chunk_size: int = 500
    chunk_overlap: int = 50
    chunk_mode: str = "fixed"
    
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
            "graph_backend": self.graph_backend,
            "graphiti_embedding_model": self.graphiti_embedding_model,
            "enable_otel_tracing": self.enable_otel_tracing,
            "enable_oracle_runtime_overrides": self.enable_oracle_runtime_overrides,
            "oracle_pool_min": self.oracle_pool_min,
            "oracle_pool_max": self.oracle_pool_max,
            "oracle_pool_increment": self.oracle_pool_increment,
            "oracle_max_coroutines": self.oracle_max_coroutines,
            "project_workspace_id": self.project_workspace_id,
            "zep_graph_address": self.zep_graph_address,
            "graph_build_task_id": self.graph_build_task_id,
            "has_built_graph": self.has_built_graph,
            "graph_resume_candidate": self.graph_resume_candidate,
            "refresh_data_while_build": self.refresh_data_while_build,
            "context_requirement": self.context_requirement,
            "prompt_label": self.prompt_label,
            "prompt_label_id": self.prompt_label_id,
            "minimum_nodes": self.minimum_nodes,
            "minimum_edges": self.minimum_edges,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunk_mode": self.chunk_mode,
            "error": self.error
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Project':
        status = data.get('status', 'created')
        if isinstance(status, str):
            status = ProjectStatus(status)
        
        zep_graph_id = data.get("zep_graph_id") or data.get("graph_id")
        graph_backend = data.get("graph_backend")
        graphiti_embedding_model = data.get("graphiti_embedding_model")
        project_workspace_id = data.get("project_workspace_id")

        has_built_graph = bool(
            data.get(
                "has_built_graph",
                str(data.get("status", "")).strip().lower() == ProjectStatus.GRAPH_COMPLETED.value,
            )
        )

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
            graph_backend=graph_backend,
            graphiti_embedding_model=graphiti_embedding_model,
            enable_otel_tracing=data.get("enable_otel_tracing"),
            enable_oracle_runtime_overrides=_as_bool(
                data.get("enable_oracle_runtime_overrides", True),
                True,
            ),
            oracle_pool_min=_as_int(data.get("oracle_pool_min"), 0) or None,
            oracle_pool_max=_as_int(data.get("oracle_pool_max"), 0) or None,
            oracle_pool_increment=_as_int(data.get("oracle_pool_increment"), 0) or None,
            oracle_max_coroutines=_as_int(data.get("oracle_max_coroutines"), 0) or None,
            project_workspace_id=project_workspace_id,
            zep_graph_address=data.get("zep_graph_address"),
            graph_build_task_id=data.get('graph_build_task_id'),
            has_built_graph=has_built_graph,
            graph_resume_candidate=data.get("graph_resume_candidate"),
            refresh_data_while_build=bool(data.get("refresh_data_while_build", True)),
            context_requirement=data.get('context_requirement'),
            prompt_label=data.get("prompt_label"),
            prompt_label_id=_as_int(data.get("prompt_label_id"), 0) or None,
            minimum_nodes=_as_int(data.get("minimum_nodes", 10), 10),
            minimum_edges=_as_int(data.get("minimum_edges", 10), 10),
            chunk_size=_as_int(data.get('chunk_size', 500), 500),
            chunk_overlap=_as_int(data.get('chunk_overlap', 50), 50),
            chunk_mode=_normalize_chunk_mode(data.get("chunk_mode", "fixed")),
            error=data.get('error')
        )
