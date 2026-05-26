"""集合类 core nodes 共享 helper。"""

from __future__ import annotations

import json

from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError


def require_list_value(
    payload: object,
    *,
    field_name: str,
    node_id: str,
) -> list[object]:
    """校验输入 payload 中的值必须为数组。

    参数：
    - payload：待校验的 value payload。
    - field_name：错误消息中使用的字段名。
    - node_id：当前节点实例 id。

    返回：
    - list[object]：复制后的列表值。
    """

    items_value = require_value_payload(payload, field_name=field_name)["value"]
    if not isinstance(items_value, list):
        raise InvalidRequestError(
            f"{field_name} payload 中的 value 必须是数组",
            details={"node_id": node_id, "field_name": field_name},
        )
    return list(items_value)


def coerce_truthy_bool(value: object) -> bool:
    """按 Python truthy 语义把 JSON 值转成布尔值。

    参数：
    - value：待转换的 JSON 值。

    返回：
    - bool：转换后的布尔结果。
    """

    return bool(value)


def build_collection_identity_key(value: object) -> str:
    """把 JSON 安全值转换为稳定的集合比较 key。

    参数：
    - value：待转换的 JSON 安全值。

    返回：
    - str：稳定的字符串 key。
    """

    normalized_value = build_value_payload(value)["value"]
    return json.dumps(normalized_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stringify_group_key(value: object, *, node_id: str, field_name: str) -> str:
    """把分组 key 规范化为对象字段可用的字符串。

    参数：
    - value：待规范化的分组 key。
    - node_id：当前节点实例 id。
    - field_name：错误消息中使用的字段名。

    返回：
    - str：规范化后的字符串 key。
    """

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    raise InvalidRequestError(
        f"{field_name} 只支持字符串、数字、布尔值或 null 作为分组 key",
        details={"node_id": node_id, "field_name": field_name, "value_type": value.__class__.__name__},
    )