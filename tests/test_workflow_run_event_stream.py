"""正式 WorkflowRun JSONL 生命周期事件流测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from backend.service.application.workflows.runtime.persistence import (
    append_workflow_run_event,
    read_workflow_run_events,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from tests.api_test_support import create_test_runtime


def test_lifecycle_events_ignore_trace_switch_and_diagnostic_events_do_not(
    tmp_path: Path,
) -> None:
    """验证关闭 trace 时仍写生命周期事件，但不写详细诊断事件。"""

    _, dataset_storage, _ = create_test_runtime(
        tmp_path,
        database_name="workflow-run-events.db",
    )
    workflow_run = _build_workflow_run("workflow-run-lifecycle")
    event_lock = Lock()
    sequence_lock = Lock()
    sequences: dict[str, int] = {}

    lifecycle_event = append_workflow_run_event(
        dataset_storage=dataset_storage,
        workflow_run=workflow_run,
        event_lock=event_lock,
        event_sequences=sequences,
        event_sequence_lock=sequence_lock,
        event_type="run.queued",
        message="queued",
    )
    diagnostic_event = append_workflow_run_event(
        dataset_storage=dataset_storage,
        workflow_run=workflow_run,
        event_lock=event_lock,
        event_sequences=sequences,
        event_sequence_lock=sequence_lock,
        event_type="node.completed",
        message="node completed",
    )

    assert lifecycle_event.sequence == 1
    assert diagnostic_event.sequence == 0
    assert [
        event.event_type
        for event in read_workflow_run_events(
            dataset_storage,
            workflow_run.workflow_run_id,
        )
    ] == ["run.queued"]


def test_workflow_run_events_resume_bad_tail_and_serialize_concurrent_writers(
    tmp_path: Path,
) -> None:
    """验证坏尾恢复、重启续号和多线程 sequence 不重复。"""

    _, dataset_storage, _ = create_test_runtime(
        tmp_path,
        database_name="workflow-run-events.db",
    )
    workflow_run = _build_workflow_run("workflow-run-concurrent")
    event_lock = Lock()
    sequence_lock = Lock()
    sequences: dict[str, int] = {}

    first_event = append_workflow_run_event(
        dataset_storage=dataset_storage,
        workflow_run=workflow_run,
        event_lock=event_lock,
        event_sequences=sequences,
        event_sequence_lock=sequence_lock,
        event_type="run.queued",
        message="queued",
    )
    events_path = dataset_storage.resolve(
        f"workflows/runtime/{workflow_run.workflow_run_id}/events.jsonl"
    )
    with events_path.open("ab") as event_stream:
        event_stream.write(b'{"sequence":999')

    restarted_sequences: dict[str, int] = {}
    resumed_event = append_workflow_run_event(
        dataset_storage=dataset_storage,
        workflow_run=workflow_run,
        event_lock=event_lock,
        event_sequences=restarted_sequences,
        event_sequence_lock=sequence_lock,
        event_type="run.started",
        message="started",
    )

    def append_terminal(index: int) -> int:
        event = append_workflow_run_event(
            dataset_storage=dataset_storage,
            workflow_run=workflow_run,
            event_lock=event_lock,
            event_sequences=restarted_sequences,
            event_sequence_lock=sequence_lock,
            event_type="run.succeeded",
            message=f"done-{index}",
            payload={"index": index},
        )
        return event.sequence

    with ThreadPoolExecutor(max_workers=8) as executor:
        concurrent_sequences = tuple(executor.map(append_terminal, range(24)))

    events = read_workflow_run_events(dataset_storage, workflow_run.workflow_run_id)

    assert first_event.sequence == 1
    assert resumed_event.sequence == 2
    assert sorted(concurrent_sequences) == list(range(3, 27))
    assert [event.sequence for event in events] == list(range(1, 27))
    assert len({event.payload.get("index") for event in events[2:]}) == 24


def _build_workflow_run(workflow_run_id: str) -> WorkflowRun:
    """构造关闭 trace 的最小正式 WorkflowRun。"""

    return WorkflowRun(
        workflow_run_id=workflow_run_id,
        workflow_runtime_id="workflow-runtime-events",
        project_id="project-1",
        application_id="application-1",
        state="queued",
        created_at="2026-08-22T00:00:00Z",
        metadata={
            "trace_level": "none",
            "retain_trace_enabled": False,
        },
    )
