"""service node 参数和对象输入 helper。"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.nodes.runtime_support import resolve_image_input
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


def require_str_parameter(request: WorkflowNodeExecutionRequest, name: str) -> str:
    """读取必填字符串参数。"""

    value = request.parameters.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            f"参数 {name} 不能为空字符串",
            details={"node_id": request.node_id, "parameter": name},
        )
    return value.strip()


def get_optional_str_parameter(request: WorkflowNodeExecutionRequest, name: str) -> str | None:
    """读取可选字符串参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRequestError(
            f"参数 {name} 必须是字符串",
            details={"node_id": request.node_id, "parameter": name},
        )
    normalized = value.strip()
    return normalized or None


def get_optional_int_parameter(request: WorkflowNodeExecutionRequest, name: str) -> int | None:
    """读取可选整数参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(
            f"参数 {name} 必须是整数",
            details={"node_id": request.node_id, "parameter": name},
        )
    return value


def get_optional_float_parameter(request: WorkflowNodeExecutionRequest, name: str) -> float | None:
    """读取可选浮点参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidRequestError(
            f"参数 {name} 必须是数字",
            details={"node_id": request.node_id, "parameter": name},
        )
    return float(value)


def get_optional_bool_parameter(request: WorkflowNodeExecutionRequest, name: str) -> bool | None:
    """读取可选布尔参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise InvalidRequestError(
            f"参数 {name} 必须是布尔值",
            details={"node_id": request.node_id, "parameter": name},
        )
    return value


def get_optional_dict_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str,
) -> dict[str, object]:
    """读取可选对象参数。"""

    value = request.parameters.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidRequestError(
            f"参数 {name} 必须是对象",
            details={"node_id": request.node_id, "parameter": name},
        )
    return {str(key): item for key, item in value.items()}


def get_optional_object_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "request",
) -> dict[str, object] | None:
    """读取可选对象 value 输入。

    参数：
    - request：当前节点执行请求。
    - input_name：对象输入端口名称。

    返回：
    - dict[str, object] | None：输入对象值；未提供时返回 None。
    """

    raw_payload = request.input_values.get(input_name)
    if raw_payload is None:
        return None
    object_value = require_value_payload(raw_payload, field_name=input_name)["value"]
    if not isinstance(object_value, dict):
        raise InvalidRequestError(
            f"输入 {input_name} 必须是对象 value payload",
            details={"node_id": request.node_id, "input_name": input_name},
        )
    return {str(key): item for key, item in object_value.items()}


def overlay_parameters_from_object_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "request",
) -> WorkflowNodeExecutionRequest:
    """把对象输入中的字段覆盖到当前节点参数上。

    参数：
    - request：当前节点执行请求。
    - input_name：对象输入端口名称。

    返回：
    - WorkflowNodeExecutionRequest：参数已合并的新执行请求。
    """

    input_object = get_optional_object_input(request, input_name=input_name)
    if not input_object:
        return request
    merged_parameters = dict(request.parameters)
    merged_parameters.update(input_object)
    return replace(request, parameters=merged_parameters)


def get_optional_str_tuple_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str,
) -> tuple[str, ...] | None:
    """读取可选字符串数组参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvalidRequestError(
            f"参数 {name} 必须是字符串数组",
            details={"node_id": request.node_id, "parameter": name},
        )
    normalized_values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise InvalidRequestError(
                f"参数 {name} 的每一项都必须是非空字符串",
                details={"node_id": request.node_id, "parameter": name},
            )
        normalized_values.append(item.strip())
    return tuple(normalized_values)


def get_optional_int_pair_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str,
) -> tuple[int, int] | None:
    """读取可选的两个整数参数。"""

    value = request.parameters.get(name)
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence) or len(value) != 2:
        raise InvalidRequestError(
            f"参数 {name} 必须是长度为 2 的整数数组",
            details={"node_id": request.node_id, "parameter": name},
        )
    first, second = value[0], value[1]
    if isinstance(first, bool) or not isinstance(first, int):
        raise InvalidRequestError(
            f"参数 {name} 的第一个值必须是整数",
            details={"node_id": request.node_id, "parameter": name},
        )
    if isinstance(second, bool) or not isinstance(second, int):
        raise InvalidRequestError(
            f"参数 {name} 的第二个值必须是整数",
            details={"node_id": request.node_id, "parameter": name},
        )
    return (first, second)


def get_optional_image_object_key(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "image",
) -> str | None:
    """读取可选 image-ref 输入并返回 object key。"""

    if request.input_values.get(input_name) is None:
        return None
    _, _, object_key = resolve_image_input(request, input_name=input_name)
    return object_key


def resolve_created_by(request: WorkflowNodeExecutionRequest) -> str | None:
    """解析 service 调用使用的 created_by。"""

    parameter_value = get_optional_str_parameter(request, "created_by")
    if parameter_value is not None:
        return parameter_value
    metadata_value = request.execution_metadata.get("created_by")
    if isinstance(metadata_value, str) and metadata_value.strip():
        return metadata_value.strip()
    return None


def resolve_display_name(request: WorkflowNodeExecutionRequest) -> str:
    """解析 service 调用使用的 display_name。"""

    parameter_value = get_optional_str_parameter(request, "display_name")
    if parameter_value is not None:
        return parameter_value
    metadata_value = request.execution_metadata.get("display_name")
    if isinstance(metadata_value, str) and metadata_value.strip():
        return metadata_value.strip()
    return ""


def require_runtime_mode_parameter(
    request: WorkflowNodeExecutionRequest,
    name: str = "runtime_mode",
) -> str:
    """读取并校验 deployment runtime_mode 参数。"""

    runtime_mode = require_str_parameter(request, name)
    if runtime_mode not in {"sync", "async"}:
        raise InvalidRequestError(
            f"参数 {name} 只能是 sync 或 async",
            details={"node_id": request.node_id, "parameter": name},
        )
    return runtime_mode


def require_service_task_type_parameter(
    request: WorkflowNodeExecutionRequest,
) -> str:
    """读取并校验 service node 的必填 task_type 参数。"""

    task_type = get_optional_str_parameter(request, "task_type")
    if task_type is None:
        raise InvalidRequestError(
            "task_type 不能为空，service node 必须显式声明任务分类",
            details={"node_id": request.node_id, "parameter": "task_type"},
        )
    normalized_task_type = task_type.strip().lower()
    supported_task_types = {
        DETECTION_TASK_TYPE,
        CLASSIFICATION_TASK_TYPE,
        SEGMENTATION_TASK_TYPE,
        POSE_TASK_TYPE,
        OBB_TASK_TYPE,
    }
    if normalized_task_type not in supported_task_types:
        raise InvalidRequestError(
            "task_type 不受当前 service node 支持",
            details={
                "node_id": request.node_id,
                "task_type": task_type,
                "supported": sorted(supported_task_types),
            },
        )
    return normalized_task_type
