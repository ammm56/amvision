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
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


WORKFLOW_SERVICE_TASK_TYPES: tuple[str, ...] = (
    DETECTION_TASK_TYPE,
    CLASSIFICATION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    POSE_TASK_TYPE,
    OBB_TASK_TYPE,
)
WORKFLOW_SERVICE_MODEL_TYPES: tuple[str, ...] = (
    "yolox",
    "yolov8",
    "yolo11",
    "yolo26",
    "rfdetr",
)
WORKFLOW_SERVICE_MODEL_SCALES: tuple[str, ...] = (
    "nano",
    "tiny",
    "s",
    "m",
    "l",
    "x",
    "xx",
)
WORKFLOW_SERVICE_MODEL_TYPES_BY_TASK_TYPE: dict[str, tuple[str, ...]] = {
    DETECTION_TASK_TYPE: ("yolox", "yolov8", "yolo11", "yolo26", "rfdetr"),
    CLASSIFICATION_TASK_TYPE: ("yolov8", "yolo11", "yolo26"),
    SEGMENTATION_TASK_TYPE: ("yolov8", "yolo11", "yolo26", "rfdetr"),
    POSE_TASK_TYPE: ("yolov8", "yolo11", "yolo26"),
    OBB_TASK_TYPE: ("yolov8", "yolo11", "yolo26"),
}


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

    return WORKFLOW_SERVICE_MODEL_TYPES_BY_TASK_TYPE.get(task_type, WORKFLOW_SERVICE_MODEL_TYPES)
