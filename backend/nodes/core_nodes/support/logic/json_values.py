"""JSON 安全值规范化 helper。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


def normalize_json_safe_value(value: object) -> object:
    """把值递归规范化为 JSON 安全结构。"""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return [normalize_json_safe_value(item) for item in value]
    if isinstance(value, list):
        return [normalize_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_json_safe_value(item) for key, item in value.items()}
    raise InvalidRequestError(
        "当前逻辑节点只支持 JSON 安全值",
        details={"value_type": value.__class__.__name__},
    )
