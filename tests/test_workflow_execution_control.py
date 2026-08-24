"""Workflow ExecutionControl 测试。"""

from __future__ import annotations

from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

from backend.service.application.errors import (
    OperationCancelledError,
    OperationTimeoutError,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.execution.execution_control import (
    WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY,
    build_node_execution_control,
    prepare_execution_control_metadata,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY,
    build_process_safe_execution_metadata,
)


def _build_request(
    *,
    cancellation_event: Event | None = None,
    execution_metadata: dict[str, object] | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造 ExecutionControl 单元测试请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="wait-node",
        node_definition=SimpleNamespace(node_type_id="test.wait"),
        execution_metadata=execution_metadata or {},
        node_cancellation_event=cancellation_event,
    )


def test_execution_control_rejects_cancelled_request() -> None:
    """已经取消的节点不能进入下一次轮询。"""

    cancellation_event = Event()
    cancellation_event.set()
    control = build_node_execution_control(
        _build_request(cancellation_event=cancellation_event)
    )

    with pytest.raises(OperationCancelledError):
        control.raise_if_cancelled_or_expired()


def test_execution_control_uses_earliest_deadline() -> None:
    """操作 timeout 应与 Workflow deadline 取最早值。"""

    workflow_deadline = monotonic() + 10.0
    control = build_node_execution_control(
        _build_request(
            execution_metadata={
                WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY: workflow_deadline
            }
        ),
        operation_timeout_seconds=0.01,
    )

    assert control.deadline_monotonic is not None
    assert control.deadline_monotonic < workflow_deadline


def test_execution_control_includes_node_pack_deadline() -> None:
    """Node Pack deadline 必须作为 handler 可见的协作式 deadline。"""

    node_deadline = monotonic() + 0.01
    request = _build_request()
    request = WorkflowNodeExecutionRequest(
        node_id=request.node_id,
        node_definition=request.node_definition,
        node_deadline_monotonic=node_deadline,
    )

    control = build_node_execution_control(request)

    assert control.deadline_monotonic == node_deadline


def test_execution_control_preserves_workflow_timeout_error_when_it_is_earlier() -> None:
    """Node Pack policy 较长时仍应保留 Workflow 总 deadline 的公开错误语义。"""

    workflow_deadline = monotonic() - 0.01
    request = WorkflowNodeExecutionRequest(
        node_id="wait-node",
        node_definition=SimpleNamespace(node_type_id="test.wait"),
        execution_metadata={
            WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY: workflow_deadline
        },
        node_deadline_monotonic=workflow_deadline,
    )

    with pytest.raises(OperationTimeoutError, match="Workflow 执行超过 deadline"):
        build_node_execution_control(request).raise_if_cancelled_or_expired()


def test_execution_control_wait_honors_deadline() -> None:
    """可中断等待不能越过节点 deadline。"""

    control = build_node_execution_control(
        _build_request(),
        operation_timeout_seconds=0.01,
    )

    with pytest.raises(OperationTimeoutError):
        control.wait_interruptibly(1.0)


def test_execution_deadline_is_created_once_and_not_cross_process_serialized() -> None:
    """deadline 在执行进程创建一次，发送到子进程前移除。"""

    metadata: dict[str, object] = {
        WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY: 5.0
    }
    first = prepare_execution_control_metadata(metadata)
    second = prepare_execution_control_metadata(metadata)

    assert first == second
    assert first is not None
    assert WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY not in (
        build_process_safe_execution_metadata(metadata)
    )
