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

import threading
import uuid
import os
from datetime import datetime, timedelta
import logging

from app.core.config import Config
from app.core.schemas.task import Task, TaskStatus
from app.core.utils.db_query import (
    get_graph_build_task_data,
    insert_graph_build_data,
    update_graph_build_status,
)

logger = logging.getLogger("uvicorn.error")


class TaskManager:
    _instance = None
    _lock = threading.Lock()
    _POSTGRES_STORAGE_VALUES = {"postgres", "postgrel", "postgresql"}
    _PERSISTED_ACTIVE_STATUS = {"pending", "processing"}
    _PERSISTED_ACTIVE_MAX_AGE_SECONDS = 300
    _GRAPH_BUILD_PERSIST_MIN_INTERVAL_SECONDS = 120
    _WORKER_STARTED_AT = datetime.now().isoformat()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
                    cls._instance._last_graph_build_persisted_at: dict[str, datetime] = {}
        return cls._instance

    @classmethod
    def _use_postgres_storage(cls) -> bool:
        return str(Config.STORAGE).strip().lower() in cls._POSTGRES_STORAGE_VALUES

    @classmethod
    def _get_storage_connection_string(cls) -> str:
        return str(Config.PROJECT_STORAGE_CONNECTION_STRING or "").strip()

    @staticmethod
    def _is_graph_build_task(task_type: str) -> bool:
        normalized = str(task_type or "").strip().lower()
        return normalized == "graph_build"

    @staticmethod
    def _as_int_or_none(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _persist_graph_build_task(
        self,
        task: Task | None,
        *,
        is_create: bool = False,
        force: bool = False,
    ) -> None:
        if task is None:
            return
        if not self._is_graph_build_task(task.task_type):
            return
        if not self._use_postgres_storage():
            return

        connection_string = self._get_storage_connection_string()
        if not connection_string:
            return

        metadata = dict(task.metadata or {})
        result = task.result if isinstance(task.result, dict) else {}
        project_id = str(
            metadata.get("project_id")
            or result.get("project_id")
            or ""
        ).strip() or None
        graph_id = str(
            result.get("zep_graph_id")
            or result.get("graph_id")
            or metadata.get("graph_id")
            or ""
        ).strip() or None
        graph_name = str(metadata.get("graph_name") or "").strip() or None
        graph_backend = str(
            metadata.get("graph_backend")
            or result.get("graph_backend")
            or ""
        ).strip().lower() or None
        chunk_mode = str(
            metadata.get("chunk_mode")
            or result.get("chunk_mode")
            or ""
        ).strip().lower() or None
        chunk_size = self._as_int_or_none(metadata.get("chunk_size"))
        chunk_overlap = self._as_int_or_none(metadata.get("chunk_overlap"))
        source_text_hash = str(
            metadata.get("source_text_hash")
            or result.get("source_text_hash")
            or ""
        ).strip() or None
        ontology_hash = str(
            metadata.get("ontology_hash")
            or result.get("ontology_hash")
            or ""
        ).strip() or None
        progress_detail = dict(task.progress_detail or {})
        ontology_version_id = self._as_int_or_none(
            metadata.get("ontology_version_id")
            or progress_detail.get("ontology_version_id")
            or result.get("ontology_version_id")
        )
        build_identity_key = str(
            metadata.get("build_identity_key")
            or result.get("build_identity_key")
            or ""
        ).strip() or None
        batch_size = self._as_int_or_none(
            metadata.get("batch_size")
            or progress_detail.get("batch_size")
            or result.get("batch_size")
        )
        total_chunks = self._as_int_or_none(
            metadata.get("total_chunks")
            or progress_detail.get("total_chunks")
            or result.get("total_chunks")
        )
        total_batches = self._as_int_or_none(
            metadata.get("total_batches")
            or progress_detail.get("total_batches")
            or result.get("total_batches")
        )
        last_completed_batch_index = self._as_int_or_none(
            progress_detail.get("last_completed_batch_index")
            if progress_detail.get("last_completed_batch_index") is not None
            else metadata.get("last_completed_batch_index")
        )
        resume_state = str(
            progress_detail.get("resume_state")
            or metadata.get("resume_state")
            or result.get("resume_state")
            or ""
        ).strip() or None
        status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
        now_dt = task.updated_at if isinstance(task.updated_at, datetime) else datetime.now()
        is_terminal = status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }

        try:
            if is_create:
                insert_graph_build_data(
                    connection_string,
                    task_id=task.task_id,
                    task_type=task.task_type,
                    project_id=project_id,
                    graph_id=graph_id,
                    graph_name=graph_name,
                    graph_backend=graph_backend,
                    chunk_mode=chunk_mode,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    status=status,
                    progress=task.progress,
                    message=task.message,
                    error=task.error,
                    result=result if result else None,
                    progress_detail=progress_detail,
                    source_text_hash=source_text_hash,
                    ontology_hash=ontology_hash,
                    ontology_version_id=ontology_version_id,
                    build_identity_key=build_identity_key,
                    batch_size=batch_size,
                    total_chunks=total_chunks,
                    total_batches=total_batches,
                    last_completed_batch_index=last_completed_batch_index,
                    resume_state=resume_state,
                    created_at=task.created_at.isoformat(),
                    updated_at=task.updated_at.isoformat(),
                )
                self._last_graph_build_persisted_at[task.task_id] = now_dt
                return

            last_persisted = self._last_graph_build_persisted_at.get(task.task_id)
            if not force and not is_terminal and last_persisted is not None:
                elapsed_seconds = (now_dt - last_persisted).total_seconds()
                if elapsed_seconds < self._GRAPH_BUILD_PERSIST_MIN_INTERVAL_SECONDS:
                    return

            updated = update_graph_build_status(
                connection_string,
                task_id=task.task_id,
                status=status,
                progress=task.progress,
                message=task.message,
                error=task.error,
                result=result if result else None,
                progress_detail=progress_detail,
                source_text_hash=source_text_hash,
                ontology_hash=ontology_hash,
                ontology_version_id=ontology_version_id,
                build_identity_key=build_identity_key,
                chunk_mode=chunk_mode,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                updated_at=task.updated_at.isoformat(),
            )
            if updated:
                self._last_graph_build_persisted_at[task.task_id] = now_dt
        except Exception:
            logger.exception("Failed to persist graph_build task state: task_id=%s", task.task_id)

    def _is_recent_persisted_active_task(self, task_id: str) -> bool:
        if not self._use_postgres_storage():
            return False

        connection_string = self._get_storage_connection_string()
        if not connection_string:
            return False

        try:
            persisted = get_graph_build_task_data(connection_string, task_id)
            if not persisted:
                return False
            if not self._is_graph_build_task(str(persisted.get("task_type") or "")):
                return False

            status = str(persisted.get("status") or "").strip().lower()
            if status not in self._PERSISTED_ACTIVE_STATUS:
                return False

            updated_at_raw = str(persisted.get("updated_at") or "").strip()
            if not updated_at_raw:
                # Conservative: active status with no timestamp should still block.
                return True

            updated_at = datetime.fromisoformat(updated_at_raw)
            age_seconds = (datetime.now() - updated_at).total_seconds()
            return age_seconds <= self._PERSISTED_ACTIVE_MAX_AGE_SECONDS
        except Exception:
            logger.exception(
                "Failed to read persisted graph_build activity state: task_id=%s",
                task_id,
            )
            return False
    
    def create_task(self, task_type: str, metadata: dict | None = None) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now()
        task_metadata = dict(metadata or {})
        task_metadata.setdefault("_worker_pid", str(os.getpid()))
        task_metadata.setdefault("_worker_started_at", self._WORKER_STARTED_AT)
        
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=task_metadata
        )
        
        task_for_persistence: Task | None = None
        with self._task_lock:
            self._tasks[task_id] = task
            task_for_persistence = task

        self._persist_graph_build_task(task_for_persistence, is_create=True, force=True)
        
        return task_id
    
    def get_task(self, task_id: str) -> Task | None:
        with self._task_lock:
            return self._tasks.get(task_id)
    
    def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict | None = None,
        error: str | None = None,
        progress_detail: dict | None = None
    ):
        task_for_persistence: Task | None = None
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                # Keep cancelled tasks immutable to prevent worker threads from
                # overwriting cancellation with later progress/completed updates.
                if task.status == TaskStatus.CANCELLED and status != TaskStatus.CANCELLED:
                    return
                task.updated_at = datetime.now()
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                if progress_detail is not None:
                    merged_progress_detail = dict(task.progress_detail or {})
                    merged_progress_detail.update(progress_detail)
                    task.progress_detail = merged_progress_detail
                task_for_persistence = task

        normalized_status = (
            status.value if isinstance(status, TaskStatus) else str(status or "").strip().lower()
        )
        force_persist = normalized_status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }
        self._persist_graph_build_task(task_for_persistence, force=force_persist)
    
    def complete_task(self, task_id: str, result: dict):
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="Task Done",
            result=result
        )
    
    def fail_task(self, task_id: str, error: str):
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message="Task Failed",
            error=error
        )

    def cancel_task(self, task_id: str, message: str = "Task cancelled by user") -> bool:
        task_for_persistence: Task | None = None
        cancelled = False
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                return False
            task.updated_at = datetime.now()
            task.status = TaskStatus.CANCELLED
            task.message = message
            task.error = None
            task_for_persistence = task
            cancelled = True
        self._persist_graph_build_task(task_for_persistence, force=True)
        return cancelled

    def is_cancelled(self, task_id: str) -> bool:
        with self._task_lock:
            task = self._tasks.get(task_id)
            return bool(task and task.status == TaskStatus.CANCELLED)

    def graph_build_task_is_active(self, task_id: str | None) -> bool:
        """
        True if graph_build is active in memory, or persisted as recently active in
        Postgres storage. This keeps "building" sticky across frontend reconnects
        and multi-worker API requests, while still recovering stale state after
        hard backend restarts where heartbeat-like task updates stop.
        """
        normalized = str(task_id or "").strip()
        if not normalized:
            return False
        with self._task_lock:
            task = self._tasks.get(normalized)
        if task and self._is_graph_build_task(task.task_type):
            return task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING}
        return self._is_recent_persisted_active_task(normalized)

    def list_tasks(self, task_type: str | None = None) -> list:
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                ]
            ]
            for tid in old_ids:
                del self._tasks[tid]
                self._last_graph_build_persisted_at.pop(tid, None)

