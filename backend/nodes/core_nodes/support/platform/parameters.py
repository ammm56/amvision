"""workflow service node 平台参数读取与校验。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.platform.constants import (
    WORKFLOW_SERVICE_MODEL_TYPES,
    WORKFLOW_SERVICE_TASK_TYPES,
)
from backend.nodes.core_nodes.support.service import get_optional_str_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.platform_model_support import (
    get_supported_platform_model_types as get_registered_platform_model_types,
)


def get_optional_platform_task_type(request: WorkflowNodeExecutionRequest) -> str | None:
    """读取并校验可选 task_type。"""

    task_type = get_optional_str_parameter(request, "task_type")
    if task_type is None:
        return None
    if task_type not in WORKFLOW_SERVICE_TASK_TYPES:
        raise InvalidRequestError(
            "task_type 不受当前 workflow service node 支持",
            details={
                "node_id": request.node_id,
                "task_type": task_type,
                "supported": list(WORKFLOW_SERVICE_TASK_TYPES),
            },
        )
    return task_type


def require_platform_task_type(request: WorkflowNodeExecutionRequest) -> str:
    """读取并校验必填 task_type。"""

    task_type = get_optional_platform_task_type(request)
    if task_type is not None:
        return task_type
    raise InvalidRequestError(
        "task_type 不能为空，workflow service node 必须显式声明任务分类",
        details={
            "node_id": request.node_id,
            "supported": list(WORKFLOW_SERVICE_TASK_TYPES),
        },
    )


def get_optional_platform_model_type(
    request: WorkflowNodeExecutionRequest,
    *,
    supported_model_types: tuple[str, ...] = WORKFLOW_SERVICE_MODEL_TYPES,
) -> str | None:
    """读取并校验可选 model_type。"""

    model_type = get_optional_str_parameter(request, "model_type")
    if model_type is None:
        return None
    if model_type not in supported_model_types:
        raise InvalidRequestError(
            "model_type 不受当前 workflow service node 支持",
            details={
                "node_id": request.node_id,
                "model_type": model_type,
                "supported": list(supported_model_types),
            },
        )
    return model_type


def require_platform_model_type(
    request: WorkflowNodeExecutionRequest,
    *,
    supported_model_types: tuple[str, ...] = WORKFLOW_SERVICE_MODEL_TYPES,
) -> str:
    """读取并校验必填 model_type。"""

    model_type = get_optional_platform_model_type(
        request,
        supported_model_types=supported_model_types,
    )
    if model_type is not None:
        return model_type
    raise InvalidRequestError(
        "model_type 不能为空，workflow service node 必须显式声明模型分类",
        details={
            "node_id": request.node_id,
            "supported": list(supported_model_types),
        },
    )


def get_supported_platform_model_types(task_type: str) -> tuple[str, ...]:
    """按 task_type 返回当前 workflow service node 允许的 model_type 列表。"""

    return get_registered_platform_model_types(task_type)

