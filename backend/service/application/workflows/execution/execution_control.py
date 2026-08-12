"""Workflow 节点取消和 monotonic deadline 控制。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import monotonic
from typing import TYPE_CHECKING

from backend.service.application.errors import (
    OperationCancelledError,
    OperationTimeoutError,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY,
)

if TYPE_CHECKING:
    from backend.service.application.workflows.execution.contracts import (
        WorkflowNodeExecutionRequest,
    )


WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY = (
    "_workflow_execution_deadline_monotonic"
)
_INTERRUPTIBLE_SLEEP_EVENT = Event()


@dataclass(frozen=True)
class ExecutionControl:
    """提供节点级取消检查、deadline 和可中断等待。"""

    node_id: str
    cancellation_event: object | None = None
    deadline_monotonic: float | None = None

    def remaining_seconds(self) -> float | None:
        """返回 deadline 剩余秒数；无 deadline 时返回 None。"""

        if self.deadline_monotonic is None:
            return None
        return max(0.0, self.deadline_monotonic - monotonic())

    def raise_if_cancelled_or_expired(self) -> None:
        """取消或 deadline 到期时抛出稳定的应用错误。"""

        if _event_is_set(self.cancellation_event):
            raise OperationCancelledError(
                "Workflow 节点执行已取消",
                details={"node_id": self.node_id},
            )
        remaining = self.remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise OperationTimeoutError(
                "Workflow 节点执行超过 deadline",
                details={"node_id": self.node_id},
            )

    def wait_interruptibly(self, seconds: float) -> None:
        """等待指定时间，并响应取消事件和 deadline。"""

        self.raise_if_cancelled_or_expired()
        requested_seconds = max(0.0, float(seconds))
        target_monotonic = monotonic() + requested_seconds
        while True:
            self.raise_if_cancelled_or_expired()
            remaining_wait = target_monotonic - monotonic()
            if remaining_wait <= 0:
                return
            remaining_deadline = self.remaining_seconds()
            wait_seconds = (
                remaining_wait
                if remaining_deadline is None
                else min(remaining_wait, remaining_deadline)
            )
            if wait_seconds <= 0:
                self.raise_if_cancelled_or_expired()
                return
            wait_method = getattr(self.cancellation_event, "wait", None)
            if callable(wait_method):
                wait_method(wait_seconds)
            else:
                _INTERRUPTIBLE_SLEEP_EVENT.wait(wait_seconds)


def prepare_execution_control_metadata(
    execution_metadata: dict[str, object],
) -> float | None:
    """在实际执行进程中一次性建立 Workflow monotonic deadline。"""

    existing = execution_metadata.get(
        WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY
    )
    if isinstance(existing, int | float) and not isinstance(existing, bool):
        return float(existing)
    timeout_seconds = execution_metadata.get(
        WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY
    )
    if (
        isinstance(timeout_seconds, int | float)
        and not isinstance(timeout_seconds, bool)
        and float(timeout_seconds) > 0
    ):
        deadline = monotonic() + float(timeout_seconds)
        execution_metadata[
            WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY
        ] = deadline
        return deadline
    return None


def build_node_execution_control(
    request: WorkflowNodeExecutionRequest,
    *,
    operation_timeout_seconds: float | None = None,
) -> ExecutionControl:
    """组合 Workflow、manifest 和节点操作 timeout。"""

    now = monotonic()
    deadlines: list[float] = []
    workflow_deadline = request.execution_metadata.get(
        WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY
    )
    if (
        isinstance(workflow_deadline, int | float)
        and not isinstance(workflow_deadline, bool)
    ):
        deadlines.append(float(workflow_deadline))
    if request.node_timeout_seconds is not None:
        deadlines.append(now + max(0.0, float(request.node_timeout_seconds)))
    if operation_timeout_seconds is not None:
        deadlines.append(now + max(0.0, float(operation_timeout_seconds)))
    return ExecutionControl(
        node_id=request.node_id,
        cancellation_event=request.node_cancellation_event,
        deadline_monotonic=min(deadlines) if deadlines else None,
    )


def _event_is_set(event: object | None) -> bool:
    """以 duck typing 读取 threading/multiprocessing Event 状态。"""

    is_set = getattr(event, "is_set", None)
    return bool(is_set()) if callable(is_set) else False


__all__ = [
    "ExecutionControl",
    "WORKFLOW_EXECUTION_DEADLINE_MONOTONIC_KEY",
    "build_node_execution_control",
    "prepare_execution_control_metadata",
]
