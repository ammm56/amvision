"""Workflow Preview JSONL 事件流测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.workflows.resource_semantics import (
    build_workflow_preview_run_events_object_key,
)
from backend.service.application.workflows.preview_run_manager import (
    WorkflowPreviewRunManager,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from tests.api_test_support import create_test_runtime


def test_preview_events_append_one_jsonl_line_without_rewriting_prefix(
    tmp_path: Path,
) -> None:
    """验证每个 Preview 事件直接追加一行，并保留已有文件前缀。"""

    manager, dataset_storage = _build_manager(tmp_path)
    preview_run_id = "preview-run-jsonl"

    manager.initialize_event_stream(preview_run_id)
    first_event, first_persist_ms = manager.append_event(
        preview_run_id,
        event_type="preview.started",
        message="started",
        payload={},
    )
    events_path = dataset_storage.resolve(
        build_workflow_preview_run_events_object_key(preview_run_id)
    )
    first_bytes = events_path.read_bytes()
    second_event, second_persist_ms = manager.append_event(
        preview_run_id,
        event_type="preview.succeeded",
        message="done",
        payload={"state": "succeeded"},
    )
    final_bytes = events_path.read_bytes()
    lines = [json.loads(line) for line in final_bytes.splitlines()]

    assert first_event.sequence == 1
    assert second_event.sequence == 2
    assert first_persist_ms >= 0
    assert second_persist_ms >= 0
    assert final_bytes.startswith(first_bytes)
    assert [item["sequence"] for item in lines] == [1, 2]
    assert [item.sequence for item in manager.list_events(preview_run_id)] == [1, 2]


def test_preview_events_resume_after_partial_tail_line(tmp_path: Path) -> None:
    """验证重启后直接追加不会与异常退出留下的半行粘连。"""

    manager, dataset_storage = _build_manager(tmp_path)
    preview_run_id = "preview-run-partial-tail"
    manager.initialize_event_stream(preview_run_id)
    manager.append_event(
        preview_run_id,
        event_type="preview.started",
        message="started",
        payload={},
    )
    manager.close()
    events_path = dataset_storage.resolve(
        build_workflow_preview_run_events_object_key(preview_run_id)
    )
    with events_path.open("ab") as event_stream:
        event_stream.write(b'{"sequence":2')
    restarted_manager = WorkflowPreviewRunManager(
        session_factory=manager.session_factory,
        dataset_storage=dataset_storage,
    )
    resumed_event, _ = restarted_manager.append_event(
        preview_run_id,
        event_type="preview.succeeded",
        message="done",
        payload={},
    )

    events = restarted_manager.list_events(preview_run_id)

    assert resumed_event.sequence == 2
    assert [event.sequence for event in events] == [1, 2]


def _build_manager(
    tmp_path: Path,
) -> tuple[WorkflowPreviewRunManager, LocalDatasetStorage]:
    """构造只用于事件读写的 Preview manager。"""

    session_factory, dataset_storage, _ = create_test_runtime(
        tmp_path,
        database_name="preview-events.db",
    )
    return (
        WorkflowPreviewRunManager(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ),
        dataset_storage,
    )
