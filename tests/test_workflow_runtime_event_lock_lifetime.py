"""Workflow run 事件写锁生命周期测试。"""

from __future__ import annotations

from gc import collect
from uuid import uuid4

from backend.service.application.workflows.runtime_service import (
    WorkflowRuntimeService,
)


def test_workflow_run_event_lock_is_shared_only_while_in_use() -> None:
    """同一 run 的并发写入共享锁，使用结束后不永久保留 Windows 句柄。"""

    workflow_run_id = f"workflow-run-lock-{uuid4().hex}"
    first = WorkflowRuntimeService._resolve_workflow_run_event_lock(workflow_run_id)
    second = WorkflowRuntimeService._resolve_workflow_run_event_lock(workflow_run_id)

    assert first is second
    assert workflow_run_id in WorkflowRuntimeService._workflow_run_event_locks

    del second
    del first
    collect()

    assert workflow_run_id not in WorkflowRuntimeService._workflow_run_event_locks
