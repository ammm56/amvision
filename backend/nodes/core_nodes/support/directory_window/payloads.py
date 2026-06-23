"""目录窗口输出 payload helper。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload


def build_window_response(
    *,
    file_records: tuple[dict[str, object], ...] | list[dict[str, object]],
    total_count: int,
    start_index: int,
    end_index: int,
    batch_size: int,
    start_source: str,
    empty_reason: str | None,
    no_work_reason: str | None,
    cursor_anchor_path: str | None,
    cursor_anchor_found: bool | None,
    has_work: bool,
) -> dict[str, object]:
    """构造目录窗口节点输出。"""

    normalized_records = [dict(record) for record in file_records]
    count = len(normalized_records)
    has_next = end_index < total_count
    window_first_path = (
        str(normalized_records[0].get("path")) if normalized_records else None
    )
    window_last_path = (
        str(normalized_records[-1].get("path")) if normalized_records else None
    )
    cursor_last_path = window_last_path or cursor_anchor_path
    cursor_value = {
        "start_index": start_index,
        "end_index": end_index,
        "next_start_index": end_index,
        "batch_size": batch_size,
        "count": count,
        "total_count": total_count,
        "has_next": has_next,
        "completed": not has_next,
        "last_path": cursor_last_path,
        "empty": count == 0,
        "has_work": has_work,
    }
    if empty_reason is not None:
        cursor_value["empty_reason"] = empty_reason
    if no_work_reason is not None:
        cursor_value["no_work_reason"] = no_work_reason
    return {
        "files": build_value_payload(normalized_records),
        "summary": build_value_payload(
            {
                "total_count": total_count,
                "start_index": start_index,
                "end_index": end_index,
                "batch_size": batch_size,
                "count": count,
                "has_next": has_next,
                "next_start_index": end_index,
                "empty": count == 0,
                "has_work": has_work,
                "empty_reason": empty_reason,
                "no_work_reason": no_work_reason,
                "start_source": start_source,
                "window_first_path": window_first_path,
                "window_last_path": window_last_path,
                "cursor_anchor_path": cursor_anchor_path,
                "cursor_anchor_found": cursor_anchor_found,
                "cursor": cursor_value,
            }
        ),
        "cursor": build_value_payload(cursor_value),
    }
