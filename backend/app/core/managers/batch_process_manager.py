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

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Config
from app.core.utils.db_query import (
    get_latest_resumable_graph_build_data,
    update_graph_build_checkpoint,
)


@dataclass
class GraphBuildResumeContext:
    start_batch_index: int
    total_batches: int
    resume_state: str
    matched_task_id: str | None = None
    matched_graph_id: str | None = None


class BatchProcessManager:
    _POSTGRES_STORAGE_VALUES = {"postgres", "postgrel", "postgresql"}

    @classmethod
    def _use_postgres_storage(cls) -> bool:
        return str(Config.STORAGE).strip().lower() in cls._POSTGRES_STORAGE_VALUES

    @classmethod
    def _get_connection_string(cls) -> str:
        return str(Config.PROJECT_STORAGE_CONNECTION_STRING or "").strip()

    def resolve_resume_context(
        self,
        *,
        project_id: str,
        build_identity_key: str,
        current_task_id: str,
        override_graph: bool,
        total_batches: int,
    ) -> GraphBuildResumeContext:
        if override_graph:
            return GraphBuildResumeContext(start_batch_index=0, total_batches=total_batches, resume_state="new")
        if not self._use_postgres_storage():
            return GraphBuildResumeContext(start_batch_index=0, total_batches=total_batches, resume_state="new")

        connection_string = self._get_connection_string()
        if not connection_string:
            return GraphBuildResumeContext(start_batch_index=0, total_batches=total_batches, resume_state="new")

        candidate = get_latest_resumable_graph_build_data(
            connection_string,
            project_id=project_id,
            build_identity_key=build_identity_key,
            exclude_task_id=current_task_id,
        )
        if not candidate:
            return GraphBuildResumeContext(start_batch_index=0, total_batches=total_batches, resume_state="new")

        start_batch_index = int(candidate.get("last_completed_batch_index") or -1) + 1
        start_batch_index = min(max(0, start_batch_index), max(0, total_batches))
        return GraphBuildResumeContext(
            start_batch_index=start_batch_index,
            total_batches=total_batches,
            resume_state="resuming",
            matched_task_id=str(candidate.get("task_id") or "").strip() or None,
            matched_graph_id=str(candidate.get("graph_id") or "").strip() or None,
        )

    def persist_checkpoint(
        self,
        *,
        task_id: str,
        batch_index: int,
        total_batches: int,
        total_chunks: int,
        batch_size: int,
        resume_state: str,
    ) -> None:
        if not self._use_postgres_storage():
            return
        connection_string = self._get_connection_string()
        if not connection_string:
            return
        update_graph_build_checkpoint(
            connection_string,
            task_id=task_id,
            last_completed_batch_index=batch_index,
            total_batches=total_batches,
            total_chunks=total_chunks,
            batch_size=batch_size,
            resume_state=resume_state,
        )
