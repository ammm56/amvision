"""目录游标规范化 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.directory_cursor.fields import (
    CURSOR_KNOWN_FIELDS,
    read_optional_bool_field,
    read_optional_cursor_path,
    read_optional_int_field,
    read_optional_string_field,
)
from backend.nodes.core_nodes.support.directory_cursor.inputs import unwrap_cursor_mapping
from backend.service.application.errors import InvalidRequestError


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
            if field_name not in CURSOR_KNOWN_FIELDS:
                normalized_cursor[field_name] = field_value

    raw_start_index = read_optional_int_field(
        raw_cursor.get("start_index"),
        node_name=node_name,
        field_name="start_index",
    )
    raw_end_index = read_optional_int_field(
        raw_cursor.get("end_index"),
        node_name=node_name,
        field_name="end_index",
    )
    raw_next_start_index = read_optional_int_field(
        raw_cursor.get("next_start_index"),
        node_name=node_name,
        field_name="next_start_index",
    )
    raw_batch_size = read_optional_int_field(
        raw_cursor.get("batch_size"),
        node_name=node_name,
        field_name="batch_size",
        allow_zero=True,
    )
    raw_count = read_optional_int_field(
        raw_cursor.get("count"),
        node_name=node_name,
        field_name="count",
        allow_zero=True,
    )
    raw_total_count = read_optional_int_field(
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

    has_next_explicit = read_optional_bool_field(
        raw_cursor.get("has_next"),
        node_name=node_name,
        field_name="has_next",
    )
    completed_explicit = read_optional_bool_field(
        raw_cursor.get("completed"),
        node_name=node_name,
        field_name="completed",
    )
    empty_explicit = read_optional_bool_field(
        raw_cursor.get("empty"),
        node_name=node_name,
        field_name="empty",
    )
    has_work_explicit = read_optional_bool_field(
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
            "last_path": read_optional_cursor_path(
                raw_cursor.get("last_path"),
                node_name=node_name,
            ),
            "empty": empty,
            "has_work": has_work,
        }
    )
    empty_reason = read_optional_string_field(
        raw_cursor.get("empty_reason"),
        node_name=node_name,
        field_name="empty_reason",
    )
    no_work_reason = read_optional_string_field(
        raw_cursor.get("no_work_reason"),
        node_name=node_name,
        field_name="no_work_reason",
    )
    if empty_reason is not None:
        normalized_cursor["empty_reason"] = empty_reason
    if no_work_reason is not None:
        normalized_cursor["no_work_reason"] = no_work_reason
    return normalized_cursor
