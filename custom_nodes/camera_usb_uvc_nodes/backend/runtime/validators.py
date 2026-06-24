"""USB / UVC 相机 runtime 参数校验工具。"""

from __future__ import annotations

from datetime import datetime, timezone
import math

from backend.service.application.errors import InvalidRequestError
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.types import CAMERA_PARAMETER_NAME_VALUES


def require_optional_request_object(payload: object) -> dict[str, object]:
    """读取可选 request(value.v1) 输入，并要求 value 必须是对象。"""

    if payload is None:
        return {}
    if not isinstance(payload, dict) or "value" not in payload:
        raise InvalidRequestError("request payload 必须是包含 value 的对象")
    raw_value = payload.get("value")
    if not isinstance(raw_value, dict):
        raise InvalidRequestError("request.value 必须是对象")
    return {str(key): raw_value[key] for key in raw_value}


def normalize_json_safe_value(value: object) -> object:
    """递归把值规范化为 JSON 安全结构。"""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return [normalize_json_safe_value(item) for item in value]
    if isinstance(value, list):
        return [normalize_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_json_safe_value(item) for key, item in value.items()}
    raise InvalidRequestError(
        "当前节点只支持 JSON 安全值",
        details={"value_type": value.__class__.__name__},
    )


def require_positive_int(raw_value: object, *, field_name: str) -> int:
    """把输入解析为正整数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return int(raw_value)


def require_non_negative_int(raw_value: object, *, field_name: str) -> int:
    """把输入解析为非负整数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return int(raw_value)


def require_optional_positive_int(raw_value: object, *, field_name: str) -> int | None:
    """把输入解析为可选正整数。"""

    if raw_value is None:
        return None
    return require_positive_int(raw_value, field_name=field_name)


def require_optional_positive_float(raw_value: object, *, field_name: str) -> float | None:
    """把输入解析为可选正浮点数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    if float(raw_value) <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(raw_value)


def require_uint8_range(
    raw_value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """把输入解析为指定闭区间内的整数。"""

    normalized_value = require_positive_int(raw_value, field_name=field_name)
    if normalized_value < minimum or normalized_value > maximum:
        raise InvalidRequestError(f"{field_name} 必须在 {minimum} 到 {maximum} 之间")
    return normalized_value


def require_bool(raw_value: object, *, field_name: str) -> bool:
    """把输入解析为布尔值。"""

    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return bool(raw_value)


def require_string(raw_value: object, *, field_name: str) -> str:
    """把输入解析为非空字符串。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_value.strip()


def require_parameter_name_list(raw_value: object) -> list[str]:
    """把输入解析为参数名列表。"""

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError("parameter_names 必须是非空数组")
    return [require_supported_parameter_name(item) for item in raw_value]


def require_parameter_value_mapping(raw_value: object) -> dict[str, object]:
    """把输入解析为参数写入对象。"""

    if not isinstance(raw_value, dict) or not raw_value:
        raise InvalidRequestError("parameter_values 必须是非空对象")
    normalized_mapping: dict[str, object] = {}
    for key, value in raw_value.items():
        normalized_mapping[require_supported_parameter_name(key)] = value
    return normalized_mapping


def require_supported_parameter_name(raw_value: object) -> str:
    """校验相机参数名是否在支持列表中。"""

    normalized_name = require_string(raw_value, field_name="parameter_name")
    if normalized_name not in CAMERA_PARAMETER_NAME_VALUES:
        raise InvalidRequestError(
            "当前节点不支持指定相机参数名",
            details={"parameter_name": normalized_name, "allowed_values": list(CAMERA_PARAMETER_NAME_VALUES)},
        )
    return normalized_name


def require_number(raw_value: object, *, field_name: str) -> float:
    """把输入解析为有限数值。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    normalized_value = float(raw_value)
    if not math.isfinite(normalized_value):
        raise InvalidRequestError(f"{field_name} 必须是有限数值")
    return normalized_value


def require_positive_or_zero_number(
    raw_value: object,
    *,
    field_name: str,
    integer_only: bool = False,
) -> int | float:
    """把输入解析为非负数。"""

    if integer_only:
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise InvalidRequestError(f"{field_name} 必须是整数")
        if raw_value < 0:
            raise InvalidRequestError(f"{field_name} 不能小于 0")
        return int(raw_value)
    normalized_value = require_number(raw_value, field_name=field_name)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def normalize_optional_text(raw_value: object) -> str | None:
    """规范化可选字符串；空值返回 None。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    return raw_value.strip()


def now_isoformat() -> str:
    """返回 UTC ISO8601 时间字符串。"""

    return datetime.now(timezone.utc).isoformat()
