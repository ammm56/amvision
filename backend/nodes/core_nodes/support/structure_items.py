"""确定性对象字段和列表项 payload 的共享实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


OBJECT_FIELD_FORMAT_ID = "amvision.object-field.v1"
LIST_ITEM_FORMAT_ID = "amvision.list-item.v1"


def build_object_field_payload(*, key: str, value: object) -> dict[str, object]:
    """构造键和值不可拆分的对象字段 payload。"""

    return {
        "format_id": OBJECT_FIELD_FORMAT_ID,
        "key": normalize_object_field_key(key),
        "value": value,
    }


def require_object_field_payload(
    raw_payload: object,
    *,
    field_name: str,
) -> tuple[str, object]:
    """校验并读取 ``object-field.v1`` payload。"""

    if not isinstance(raw_payload, dict):
        raise InvalidRequestError(
            f"{field_name} 必须是 object-field.v1",
            details={"field_name": field_name, "reason": "payload must be an object"},
        )
    if raw_payload.get("format_id") != OBJECT_FIELD_FORMAT_ID:
        raise InvalidRequestError(
            f"{field_name} 的 format_id 无效",
            details={
                "field_name": field_name,
                "expected_format_id": OBJECT_FIELD_FORMAT_ID,
                "actual_format_id": raw_payload.get("format_id"),
            },
        )
    if "value" not in raw_payload:
        raise InvalidRequestError(
            f"{field_name} 缺少 value",
            details={"field_name": field_name, "payload_path": ["value"]},
        )
    raw_key = raw_payload.get("key")
    if not isinstance(raw_key, str):
        raise InvalidRequestError(
            f"{field_name} 的 key 必须是字符串",
            details={"field_name": field_name, "payload_path": ["key"]},
        )
    return normalize_object_field_key(raw_key), raw_payload["value"]


def normalize_object_field_key(raw_key: str) -> str:
    """校验对象字段名，不执行会改变公开 key 的隐式修剪。"""

    if not raw_key:
        raise InvalidRequestError("对象字段名不能为空")
    if raw_key != raw_key.strip():
        raise InvalidRequestError("对象字段名不能包含首尾空白字符")
    if len(raw_key) > 256:
        raise InvalidRequestError(
            "对象字段名长度不能超过 256 个字符",
            details={"actual_length": len(raw_key), "maximum_length": 256},
        )
    if any(ord(character) < 32 for character in raw_key):
        raise InvalidRequestError("对象字段名不能包含控制字符")
    return raw_key


def build_list_item_payload(*, index: object, value: object) -> dict[str, object]:
    """构造带显式顺序编号的列表项 payload。"""

    return {
        "format_id": LIST_ITEM_FORMAT_ID,
        "index": normalize_list_item_index(index),
        "value": value,
    }


def require_list_item_payload(
    raw_payload: object,
    *,
    field_name: str,
) -> tuple[int, object]:
    """校验并读取 ``list-item.v1`` payload。"""

    if not isinstance(raw_payload, dict):
        raise InvalidRequestError(
            f"{field_name} 必须是 list-item.v1",
            details={"field_name": field_name, "reason": "payload must be an object"},
        )
    if raw_payload.get("format_id") != LIST_ITEM_FORMAT_ID:
        raise InvalidRequestError(
            f"{field_name} 的 format_id 无效",
            details={
                "field_name": field_name,
                "expected_format_id": LIST_ITEM_FORMAT_ID,
                "actual_format_id": raw_payload.get("format_id"),
            },
        )
    if "value" not in raw_payload:
        raise InvalidRequestError(
            f"{field_name} 缺少 value",
            details={"field_name": field_name, "payload_path": ["value"]},
        )
    return normalize_list_item_index(raw_payload.get("index")), raw_payload["value"]


def normalize_list_item_index(raw_index: object) -> int:
    """读取非负列表项顺序编号。"""

    if isinstance(raw_index, bool) or not isinstance(raw_index, int):
        raise InvalidRequestError(
            "列表项 index 必须是非负整数",
            details={"index": raw_index},
        )
    if raw_index < 0:
        raise InvalidRequestError(
            "列表项 index 必须是非负整数",
            details={"index": raw_index},
        )
    return raw_index
