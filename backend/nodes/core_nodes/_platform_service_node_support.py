"""workflow service nodes 的平台参数辅助函数。"""

from __future__ import annotations

from backend.nodes.core_nodes._service_node_support import (
    get_optional_str_parameter,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.domain.models.platform_model_support import (
    SUPPORTED_PLATFORM_MODEL_TYPES,
    get_supported_platform_model_types as get_registered_platform_model_types,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


WORKFLOW_SERVICE_TASK_TYPES: tuple[str, ...] = (
    DETECTION_TASK_TYPE,
    CLASSIFICATION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    POSE_TASK_TYPE,
    OBB_TASK_TYPE,
)
WORKFLOW_SERVICE_MODEL_TYPES: tuple[str, ...] = SUPPORTED_PLATFORM_MODEL_TYPES
WORKFLOW_SERVICE_MODEL_SCALES: tuple[str, ...] = (
    "nano",
    "tiny",
    "s",
    "m",
    "l",
    "x",
    "xx",
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


def build_platform_task_type_parameter_schema() -> dict[str, object]:
    """返回统一 task_type 参数 schema。"""

    return {
        "type": "string",
        "enum": list(WORKFLOW_SERVICE_TASK_TYPES),
    }


def build_platform_model_type_parameter_schema(*, task_type: str | None = None) -> dict[str, object]:
    """返回统一 model_type 参数 schema。"""

    return {
        "type": "string",
        "enum": list(
            WORKFLOW_SERVICE_MODEL_TYPES if task_type is None else get_supported_platform_model_types(task_type)
        ),
    }


def build_platform_task_model_type_schema_guards() -> list[dict[str, object]]:
    """返回 task_type -> model_type 的条件 schema。"""

    return [
        {
            "if": {
                "properties": {
                    "task_type": {"const": task_type},
                }
            },
            "then": {
                "properties": {
                    "model_type": build_platform_model_type_parameter_schema(task_type=task_type),
                }
            },
        }
        for task_type in WORKFLOW_SERVICE_TASK_TYPES
    ]
