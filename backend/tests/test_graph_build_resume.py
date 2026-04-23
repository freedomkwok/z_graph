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

Regression: after a hard restart, a new graph_build task upserts a fresh graph_build row
before resume resolution. That row has the newest updated_at, so the DB query must exclude
the current task_id; otherwise resume always sees an empty checkpoint and starts at batch 0.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.core.api.project import (
    CHUNK_MODE_LLAMA_INDEX,
    SUPPORTED_CHUNK_MODES,
    _merge_ontology_payload,
    _resolve_chunk_params_for_mode,
)
from app.core.managers.batch_process_manager import BatchProcessManager
from app.core.managers.task_manager import TaskManager
from app.core.schemas.task import TaskStatus


@pytest.fixture
def batch_manager() -> BatchProcessManager:
    return BatchProcessManager()


@pytest.fixture
def fresh_task_manager() -> TaskManager:
    TaskManager._instance = None
    manager = TaskManager()
    yield manager
    TaskManager._instance = None


@patch("app.core.managers.batch_process_manager.get_latest_resumable_graph_build_data")
@patch.object(BatchProcessManager, "_get_connection_string", return_value="postgresql://test/db")
@patch.object(BatchProcessManager, "_use_postgres_storage", return_value=True)
def test_resolve_resume_passes_exclude_task_id_to_lookup(
    _use_pg: object,
    _conn: object,
    mock_get_latest,
    batch_manager: BatchProcessManager,
) -> None:
    mock_get_latest.return_value = {
        "task_id": "previous-task-id",
        "project_id": "proj-1",
        "graph_id": "graph-z",
        "status": "processing",
        "last_completed_batch_index": 2,
        "updated_at": "2026-01-01T00:00:00",
    }

    ctx = batch_manager.resolve_resume_context(
        project_id="proj-1",
        build_identity_key="identity-key",
        current_task_id="brand-new-task-id",
        override_graph=False,
        total_batches=10,
    )

    mock_get_latest.assert_called_once()
    call_kw = mock_get_latest.call_args.kwargs
    assert call_kw["project_id"] == "proj-1"
    assert call_kw["build_identity_key"] == "identity-key"
    assert call_kw["exclude_task_id"] == "brand-new-task-id"

    assert ctx.resume_state == "resuming"
    assert ctx.start_batch_index == 3
    assert ctx.matched_task_id == "previous-task-id"
    assert ctx.matched_graph_id == "graph-z"


@patch.object(BatchProcessManager, "_use_postgres_storage", return_value=False)
def test_resolve_resume_skips_db_when_not_postgres_storage(
    _use_pg: object,
    batch_manager: BatchProcessManager,
) -> None:
    ctx = batch_manager.resolve_resume_context(
        project_id="proj-1",
        build_identity_key="identity-key",
        current_task_id="any-task",
        override_graph=False,
        total_batches=5,
    )
    assert ctx.resume_state == "new"
    assert ctx.start_batch_index == 0


def test_resolve_resume_override_graph_forces_fresh_start(batch_manager: BatchProcessManager) -> None:
    ctx = batch_manager.resolve_resume_context(
        project_id="proj-1",
        build_identity_key="identity-key",
        current_task_id="any-task",
        override_graph=True,
        total_batches=5,
    )
    assert ctx.resume_state == "new"
    assert ctx.start_batch_index == 0


@patch("app.core.managers.batch_process_manager.get_latest_resumable_graph_build_data")
@patch.object(BatchProcessManager, "_get_connection_string", return_value="postgresql://test/db")
@patch.object(BatchProcessManager, "_use_postgres_storage", return_value=True)
def test_resolve_resume_caps_start_index_to_total_batches(
    _use_pg: object,
    _conn: object,
    mock_get_latest,
    batch_manager: BatchProcessManager,
) -> None:
    mock_get_latest.return_value = {
        "task_id": "t-old",
        "last_completed_batch_index": 99,
    }

    ctx = batch_manager.resolve_resume_context(
        project_id="p",
        build_identity_key="k",
        current_task_id="t-new",
        override_graph=False,
        total_batches=3,
    )
    assert ctx.start_batch_index == 3


def test_llama_index_mode_is_supported_and_uses_negative_chunk_params() -> None:
    assert CHUNK_MODE_LLAMA_INDEX in SUPPORTED_CHUNK_MODES
    chunk_size, chunk_overlap = _resolve_chunk_params_for_mode(
        chunk_mode=CHUNK_MODE_LLAMA_INDEX,
        chunk_size_value=500,
        chunk_overlap_value=50,
    )
    assert chunk_size == -1
    assert chunk_overlap == -1


@patch("app.core.managers.task_manager.update_graph_build_status")
@patch("app.core.managers.task_manager.insert_graph_build_data")
@patch.object(TaskManager, "_get_storage_connection_string", return_value="postgresql://test/db")
@patch.object(TaskManager, "_use_postgres_storage", return_value=True)
def test_graph_build_create_persists_identity_fields(
    _use_pg: object,
    _connection: object,
    mock_insert,
    mock_update,
    fresh_task_manager: TaskManager,
) -> None:
    task_id = fresh_task_manager.create_task(
        "graph_build",
        metadata={
            "project_id": "proj-1",
            "chunk_mode": CHUNK_MODE_LLAMA_INDEX,
            "chunk_size": -1,
            "chunk_overlap": -1,
            "source_text_hash": "source-hash-1",
            "ontology_hash": "ontology-hash-1",
            "ontology_version_id": 12,
            "build_identity_key": "identity-1",
        },
    )

    mock_insert.assert_called_once()
    create_kwargs = mock_insert.call_args.kwargs
    assert create_kwargs["task_id"] == task_id
    assert create_kwargs["source_text_hash"] == "source-hash-1"
    assert create_kwargs["ontology_hash"] == "ontology-hash-1"
    assert create_kwargs["ontology_version_id"] == 12
    assert create_kwargs["build_identity_key"] == "identity-1"
    assert create_kwargs["chunk_mode"] == CHUNK_MODE_LLAMA_INDEX
    assert create_kwargs["chunk_size"] == -1
    assert create_kwargs["chunk_overlap"] == -1
    mock_update.assert_not_called()


@patch("app.core.managers.task_manager.update_graph_build_status")
@patch("app.core.managers.task_manager.insert_graph_build_data")
@patch.object(TaskManager, "_get_storage_connection_string", return_value="postgresql://test/db")
@patch.object(TaskManager, "_use_postgres_storage", return_value=True)
def test_graph_build_update_is_throttled_but_terminal_forced(
    _use_pg: object,
    _connection: object,
    _mock_insert,
    mock_update,
    fresh_task_manager: TaskManager,
) -> None:
    task_id = fresh_task_manager.create_task(
        "graph_build",
        metadata={
            "project_id": "proj-1",
            "chunk_mode": "fixed",
            "chunk_size": 500,
            "chunk_overlap": 50,
            "source_text_hash": "source-hash-2",
            "ontology_hash": "ontology-hash-2",
            "ontology_version_id": 42,
            "build_identity_key": "identity-2",
        },
    )

    fresh_task_manager.update_task(task_id, message="heartbeat-1", progress=1)
    mock_update.assert_not_called()

    fresh_task_manager._last_graph_build_persisted_at[task_id] = datetime.now() - timedelta(
        seconds=TaskManager._GRAPH_BUILD_PERSIST_MIN_INTERVAL_SECONDS + 1
    )
    fresh_task_manager.update_task(task_id, message="heartbeat-2", progress=2)
    assert mock_update.call_count == 1
    throttled_update_kwargs = mock_update.call_args.kwargs
    assert throttled_update_kwargs["source_text_hash"] == "source-hash-2"
    assert throttled_update_kwargs["ontology_hash"] == "ontology-hash-2"
    assert throttled_update_kwargs["ontology_version_id"] == 42
    assert throttled_update_kwargs["build_identity_key"] == "identity-2"

    fresh_task_manager.update_task(
        task_id,
        status=TaskStatus.COMPLETED,
        message="done",
        progress=100,
        result={"build_identity_key": "identity-2"},
    )
    assert mock_update.call_count == 2


def test_merge_ontology_payload_appends_and_dedupes_same_name_types() -> None:
    base = {
        "entity_types": [
            {
                "name": "Person",
                "description": "base",
                "examples": ["Alice"],
                "attributes": [{"name": "age", "type": "number"}],
            }
        ],
        "edge_types": [
            {
                "name": "WORKS_FOR",
                "description": "",
                "attributes": [{"name": "since", "type": "date"}],
                "source_targets": [{"source": "Person", "target": "Company"}],
            }
        ],
    }
    incoming = {
        "entity_types": [
            {
                "name": "person",
                "description": "incoming",
                "examples": ["Alice", "Bob"],
                "attributes": [{"name": "age", "type": "number"}, {"name": "role", "type": "string"}],
            }
        ],
        "edge_types": [
            {
                "name": "works_for",
                "description": "incoming",
                "attributes": [{"name": "since", "type": "date"}, {"name": "location", "type": "string"}],
                "source_targets": [
                    {"source": "person", "target": "company"},
                    {"source": "Person", "target": "Organization"},
                ],
            }
        ],
    }

    merged = _merge_ontology_payload(base, incoming)
    merged_entity = merged["entity_types"][0]
    assert merged_entity["name"] == "Person"
    assert merged_entity["description"] == "base"
    assert merged_entity["examples"] == ["Alice", "Bob"]
    assert len(merged_entity["attributes"]) == 2

    merged_edge = merged["edge_types"][0]
    assert merged_edge["name"] == "WORKS_FOR"
    assert merged_edge["description"] == "incoming"
    assert len(merged_edge["attributes"]) == 2
    assert merged_edge["source_targets"] == [
        {"source": "Person", "target": "Company"},
        {"source": "Person", "target": "Organization"},
    ]
