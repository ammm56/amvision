"""Workflow runtime invoke 请求与同步结果。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun


@dataclass(frozen=True)
class WorkflowRuntimeSyncInvokeResult:
    """描述一次同步 WorkflowAppRuntime 调用结果。

    字段：
    - workflow_run：已持久化并完成状态回写的 WorkflowRun。
    - raw_outputs：本次同步调用返回的未脱敏 application outputs。
    - raw_template_outputs：本次同步调用返回的未脱敏 template outputs。
    - raw_node_records：本次同步调用返回的未脱敏 node_records。
    """

    workflow_run: WorkflowRun
    raw_outputs: dict[str, object] = field(default_factory=dict)
    raw_template_outputs: dict[str, object] = field(default_factory=dict)
    raw_node_records: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class WorkflowRuntimeInvokeRequest:
    """描述一次 runtime 调用请求。"""

    input_bindings: dict[str, object] | None = None
    execution_metadata: dict[str, object] | None = None
    timeout_seconds: int | None = None


def normalize_runtime_invoke_request(
    request: WorkflowRuntimeInvokeRequest,
) -> WorkflowRuntimeInvokeRequest:
    """规范化 runtime invoke 请求。"""

    if request.timeout_seconds is not None and request.timeout_seconds <= 0:
        raise InvalidRequestError("timeout_seconds 必须大于 0")
    return WorkflowRuntimeInvokeRequest(
        input_bindings=dict(request.input_bindings or {}),
        execution_metadata=dict(request.execution_metadata or {}),
        timeout_seconds=request.timeout_seconds,
    )
