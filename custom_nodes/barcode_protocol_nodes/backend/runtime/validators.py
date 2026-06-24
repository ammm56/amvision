"""Barcode/QR 节点参数校验与类型转换。"""

from __future__ import annotations

import base64

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def read_bool_parameter(
    request: WorkflowNodeExecutionRequest,
    *,
    field_name: str,
    default: bool,
) -> bool:
    """读取布尔参数，并允许有限字符串形式。"""

    raw_value = request.parameters.get(field_name, default)
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized_value = raw_value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
    if raw_value is None:
        return default
    raise InvalidRequestError(
        f"{field_name} 参数必须是布尔值",
        details={"node_id": request.node_id, "field_name": field_name},
    )


def read_optional_bool(value: object, *, default: bool) -> bool:
    """读取可选布尔值。"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
    raise InvalidRequestError("布尔参数格式无效")


def read_positive_int_parameter(
    request: WorkflowNodeExecutionRequest,
    *,
    field_name: str,
    default: int,
) -> int:
    """读取正整数参数，并在 null 或空字符串时回退默认值。"""

    raw_value = request.parameters.get(field_name)
    if raw_value in {None, ""}:
        return default
    return require_positive_int(raw_value, field_name=field_name)


def read_non_negative_float_parameter(
    request: WorkflowNodeExecutionRequest,
    *,
    field_name: str,
    default: float,
) -> float:
    """读取非负浮点参数，并在 null 或空字符串时回退默认值。"""

    raw_value = request.parameters.get(field_name)
    if raw_value in {None, ""}:
        return default
    return require_non_negative_float(raw_value, field_name=field_name)


def normalize_optional_object_key(value: object) -> str | None:
    """规范化可选 output_object_key 参数。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def require_positive_int(value: object, *, field_name: str) -> int:
    """把输入值解析为正整数。"""

    normalized_value = int(value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value


def require_non_negative_float(value: object, *, field_name: str) -> float:
    """把输入值解析为非负浮点数。"""

    normalized_value = float(value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def stringify_enum_like(value: object) -> str:
    """把 enum 或类似对象转换为稳定字符串。"""

    if value is None:
        return ""
    normalized_text = str(value).strip()
    if normalized_text:
        return normalized_text
    member_name = getattr(value, "name", None)
    return member_name if isinstance(member_name, str) else ""


def normalize_json_safe_value(value: object) -> object:
    """递归把对象转换为 JSON 安全结构。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        normalized_object: dict[str, object] = {}
        for key, item_value in value.items():
            normalized_object[str(key)] = normalize_json_safe_value(item_value)
        return normalized_object
    if isinstance(value, (list, tuple, set)):
        return [normalize_json_safe_value(item) for item in value]
    return str(value)
