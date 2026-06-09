"""目录游标节点共享 helper。"""

from __future__ import annotations

from pathlib import Path

from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


_CURSOR_INT_FIELDS = (
    "start_index",
    "end_index",
    "next_start_index",
    "batch_size",
    "count",
    "total_count",
)
_CURSOR_BOOL_FIELDS = (
    "has_next",
    "completed",
    "empty",
    "has_work",
)
_CURSOR_STRING_FIELDS = (
    "last_path",
    "empty_reason",
    "no_work_reason",
)
_CURSOR_KNOWN_FIELDS = frozenset(
    (*_CURSOR_INT_FIELDS, *_CURSOR_BOOL_FIELDS, *_CURSOR_STRING_FIELDS)
)


def read_cursor_object_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "cursor",
    default_value: object | None = None,
    node_name: str,
) -> tuple[dict[str, object], str]:
    """读取游标对象输入，支持 value.v1 和参数默认值。"""

    raw_payload = request.input_values.get(input_name)
    if raw_payload is not None:
        raw_value = require_value_payload(raw_payload, field_name=input_name)["value"]
        source = f"input.{input_name}"
    elif default_value is not None:
        raw_value = default_value
        source = "parameter.default_value"
    else:
        raw_value = {}
        source = "implicit-empty"
    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{node_name} 的 {input_name} 必须是对象")
    unwrapped_value, used_nested_cursor = unwrap_cursor_mapping(raw_value)
    if used_nested_cursor:
        source = f"{source}.cursor"
    return dict(unwrapped_value), source


def unwrap_cursor_mapping(raw_value: dict[str, object]) -> tuple[dict[str, object], bool]:
    """从可能是 summary.value 的对象中提取真正的 cursor 对象。"""

    nested_cursor = raw_value.get("cursor")
    if isinstance(nested_cursor, dict) and "last_path" not in raw_value:
        return dict(nested_cursor), True
    return dict(raw_value), False


def normalize_cursor_mapping(
    raw_cursor: dict[str, object],
    *,
    node_name: str,
    default_batch_size: int | None = None,
    preserve_extra_fields: bool = True,
) -> dict[str, object]:
    """把任意 cursor 对象规整成稳定结构。"""

    raw_cursor, _ = unwrap_cursor_mapping(raw_cursor)
    normalized_cursor: dict[str, object] = {}
    if preserve_extra_fields:
        for field_name, field_value in raw_cursor.items():
            if field_name not in _CURSOR_KNOWN_FIELDS:
                normalized_cursor[field_name] = field_value

    raw_start_index = _read_optional_int_field(
        raw_cursor.get("start_index"),
        node_name=node_name,
        field_name="start_index",
    )
    raw_end_index = _read_optional_int_field(
        raw_cursor.get("end_index"),
        node_name=node_name,
        field_name="end_index",
    )
    raw_next_start_index = _read_optional_int_field(
        raw_cursor.get("next_start_index"),
        node_name=node_name,
        field_name="next_start_index",
    )
    raw_batch_size = _read_optional_int_field(
        raw_cursor.get("batch_size"),
        node_name=node_name,
        field_name="batch_size",
        allow_zero=True,
    )
    raw_count = _read_optional_int_field(
        raw_cursor.get("count"),
        node_name=node_name,
        field_name="count",
        allow_zero=True,
    )
    raw_total_count = _read_optional_int_field(
        raw_cursor.get("total_count"),
        node_name=node_name,
        field_name="total_count",
        allow_zero=True,
    )

    start_index = raw_start_index or 0
    if raw_end_index is not None:
        end_index = raw_end_index
    elif raw_next_start_index is not None:
        end_index = raw_next_start_index
    elif raw_count is not None:
        end_index = start_index + raw_count
    else:
        end_index = start_index
    if end_index < start_index:
        raise InvalidRequestError(f"{node_name} 的 end_index 不能小于 start_index")
    next_start_index = raw_next_start_index if raw_next_start_index is not None else end_index
    if next_start_index < start_index:
        raise InvalidRequestError(f"{node_name} 的 next_start_index 不能小于 start_index")
    count = raw_count if raw_count is not None else max(end_index - start_index, 0)
    if raw_batch_size is not None:
        batch_size = raw_batch_size
    elif default_batch_size is not None:
        batch_size = default_batch_size
    else:
        batch_size = count
    total_count = (
        raw_total_count
        if raw_total_count is not None
        else max(end_index, next_start_index, count)
    )

    has_next_explicit = _read_optional_bool_field(
        raw_cursor.get("has_next"),
        node_name=node_name,
        field_name="has_next",
    )
    completed_explicit = _read_optional_bool_field(
        raw_cursor.get("completed"),
        node_name=node_name,
        field_name="completed",
    )
    empty_explicit = _read_optional_bool_field(
        raw_cursor.get("empty"),
        node_name=node_name,
        field_name="empty",
    )
    has_work_explicit = _read_optional_bool_field(
        raw_cursor.get("has_work"),
        node_name=node_name,
        field_name="has_work",
    )

    total_count_was_explicit = raw_total_count is not None
    has_next = (
        has_next_explicit
        if has_next_explicit is not None
        else (next_start_index < total_count if total_count_was_explicit else False)
    )
    completed = (
        completed_explicit
        if completed_explicit is not None
        else (
            next_start_index >= total_count and not has_next
            if total_count_was_explicit
            else False
        )
    )
    empty = empty_explicit if empty_explicit is not None else count == 0
    has_work = has_work_explicit if has_work_explicit is not None else count > 0

    normalized_cursor.update(
        {
            "start_index": start_index,
            "end_index": end_index,
            "next_start_index": next_start_index,
            "batch_size": batch_size,
            "count": count,
            "total_count": total_count,
            "has_next": has_next,
            "completed": completed,
            "last_path": _read_optional_cursor_path(
                raw_cursor.get("last_path"),
                node_name=node_name,
            ),
            "empty": empty,
            "has_work": has_work,
        }
    )
    empty_reason = _read_optional_string_field(
        raw_cursor.get("empty_reason"),
        node_name=node_name,
        field_name="empty_reason",
    )
    no_work_reason = _read_optional_string_field(
        raw_cursor.get("no_work_reason"),
        node_name=node_name,
        field_name="no_work_reason",
    )
    if empty_reason is not None:
        normalized_cursor["empty_reason"] = empty_reason
    if no_work_reason is not None:
        normalized_cursor["no_work_reason"] = no_work_reason
    return normalized_cursor


def _read_optional_int_field(
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


def _read_optional_bool_field(
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


def _read_optional_string_field(
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


def _read_optional_cursor_path(raw_value: object, *, node_name: str) -> str | None:
    """读取可选 cursor.last_path。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 last_path 必须是非空字符串")
    return str(Path(raw_value.strip()).expanduser().resolve())


__all__ = [
    "normalize_cursor_mapping",
    "read_cursor_object_input",
    "unwrap_cursor_mapping",
]
