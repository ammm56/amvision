"""逻辑 payload helper。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic.json_values import normalize_json_safe_value
from backend.service.application.errors import InvalidRequestError


def build_value_payload(value: object) -> dict[str, object]:
    """把任意 JSON 安全值包装成 value payload。

    参数：
    - value：要包装的值。

    返回：
    - dict[str, object]：包装后的 value payload。
    """

    return {"value": normalize_json_safe_value(value)}


def require_value_payload(payload: object, *, field_name: str = "value") -> dict[str, object]:
    """校验并规范化 value payload。

    参数：
    - payload：待校验的 payload。
    - field_name：错误消息中使用的字段名称。

    返回：
    - dict[str, object]：规范化后的 value payload。
    """

    if not isinstance(payload, dict) or "value" not in payload:
        raise InvalidRequestError(f"{field_name} payload 必须是包含 value 的对象")
    return {"value": normalize_json_safe_value(payload.get("value"))}


def build_boolean_payload(value: bool) -> dict[str, object]:
    """把布尔值包装成 boolean payload。"""

    if not isinstance(value, bool):
        raise InvalidRequestError("boolean payload 要求 value 必须是布尔值")
    return {"value": value}


def require_boolean_payload(payload: object, *, field_name: str = "condition") -> dict[str, object]:
    """校验并规范化 boolean payload。"""

    if not isinstance(payload, dict) or not isinstance(payload.get("value"), bool):
        raise InvalidRequestError(f"{field_name} payload 必须是包含布尔 value 的对象")
    return {"value": bool(payload["value"])}
