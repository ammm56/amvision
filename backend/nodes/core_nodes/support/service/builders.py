"""service node 服务构造 helper。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.service.application.workflows.service_runtime.context import (
        WorkflowServiceNodeRuntimeContext,
    )


def build_service_node_deployment_service(
    runtime_context: WorkflowServiceNodeRuntimeContext,
    *,
    task_type: str,
) -> Any:
    """按 task_type 调用 runtime_context.build_deployment_service。"""

    return runtime_context.build_deployment_service(task_type=task_type)


def build_service_node_inference_task_service(
    runtime_context: WorkflowServiceNodeRuntimeContext,
    *,
    task_type: str,
) -> Any:
    """按 task_type 调用 runtime_context.build_inference_task_service。"""

    return runtime_context.build_inference_task_service(task_type=task_type)
