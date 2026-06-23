"""装配节点参数读取 helper。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


def read_required_number(raw_value: object, *, field_name: str) -> float:
    """读取必填数值参数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    return float(raw_value)


def read_optional_non_negative_number(raw_value: object, *, field_name: str) -> float | None:
    """读取可选非负数值。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    normalized_value = float(raw_value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def read_optional_non_negative_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选非负整数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(f"{field_name} 必须是非负整数")
    return int(raw_value)


def read_optional_text(raw_value: object, *, field_name: str) -> str | None:
    """读取可选文本。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None
