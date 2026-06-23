"""目录游标字段读取 helper。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import InvalidRequestError


CURSOR_INT_FIELDS = (
    "start_index",
    "end_index",
    "next_start_index",
    "batch_size",
    "count",
    "total_count",
)
CURSOR_BOOL_FIELDS = (
    "has_next",
    "completed",
    "empty",
    "has_work",
)
CURSOR_STRING_FIELDS = (
    "last_path",
    "empty_reason",
    "no_work_reason",
)
CURSOR_KNOWN_FIELDS = frozenset(
    (*CURSOR_INT_FIELDS, *CURSOR_BOOL_FIELDS, *CURSOR_STRING_FIELDS)
)


def read_optional_int_field(
    raw_value: object,
    *,
    node_name: str,
    field_name: str,
    allow_zero: bool = False,
) -> int | None:
    """读取可选整数 cursor 字段。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是整数")
    minimum_value = 0 if allow_zero else 0
    if raw_value < minimum_value:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 不能小于 0")
    return int(raw_value)


def read_optional_bool_field(
    raw_value: object,
    *,
    node_name: str,
    field_name: str,
) -> bool | None:
    """读取可选布尔 cursor 字段。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是布尔值")
    return raw_value


def read_optional_string_field(
    raw_value: object,
    *,
    node_name: str,
    field_name: str,
) -> str | None:
    """读取可选字符串字段。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def read_optional_cursor_path(raw_value: object, *, node_name: str) -> str | None:
    """读取可选 cursor.last_path。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 last_path 必须是非空字符串")
    return str(Path(raw_value.strip()).expanduser().resolve())
