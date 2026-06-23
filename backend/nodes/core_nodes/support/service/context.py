"""service node 运行时上下文 helper。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest

if TYPE_CHECKING:
    from backend.service.application.workflows.service_runtime.context import (
        WorkflowServiceNodeRuntimeContext,
    )


def require_workflow_service_node_runtime(
    request: WorkflowNodeExecutionRequest,
) -> WorkflowServiceNodeRuntimeContext:
    """返回当前 workflow 节点执行绑定的 service runtime context。

    参数：
    - request：当前节点执行请求。

    返回：
    - WorkflowServiceNodeRuntimeContext：当前执行绑定的 service runtime context。
    """

    runtime_context = request.runtime_context
    if not _looks_like_workflow_service_runtime_context(runtime_context):
        raise ServiceConfigurationError(
            "当前 service node 缺少 WorkflowServiceNodeRuntimeContext",
            details={
                "node_id": request.node_id,
                "node_type_id": request.node_definition.node_type_id,
            },
        )
    return cast("WorkflowServiceNodeRuntimeContext", runtime_context)


def _looks_like_workflow_service_runtime_context(runtime_context: object) -> bool:
    """轻量判断当前对象是否具备 service node 所需的运行时上下文能力。"""

    if runtime_context is None:
        return False
    required_attributes = (
        "session_factory",
        "dataset_storage",
        "build_task_service",
        "build_dataset_import_service",
        "build_dataset_export_task_service",
        "build_training_task_service",
        "build_conversion_task_service",
        "build_validation_session_service",
        "build_evaluation_task_service",
        "build_deployment_service",
        "build_inference_task_service",
        "require_deployment_process_supervisor",
    )
    return all(hasattr(runtime_context, attribute_name) for attribute_name in required_attributes)
