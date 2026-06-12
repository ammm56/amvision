"""目录窗口类节点共享 helper。"""

from __future__ import annotations

from pathlib import Path

from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def read_batch_size(
    *,
    input_payload: object,
    parameter_value: object,
    node_name: str,
) -> int:
    """读取批次大小，优先使用运行时输入。"""

    raw_value = read_runtime_scalar(
        input_payload,
        field_name="batch_size",
        node_name=node_name,
    )
    if raw_value is None:
        raw_value = parameter_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 batch_size 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 batch_size 必须大于 0")
    return raw_value


def read_start_index(
    *,
    input_payload: object,
    parameter_value: object,
    node_name: str,
) -> int:
    """读取批次起始索引，优先使用运行时输入。"""

    raw_value = read_runtime_scalar(
        input_payload,
        field_name="start_index",
        node_name=node_name,
    )
    if raw_value is None:
        raw_value = parameter_value
    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 start_index 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{node_name} 的 start_index 不能小于 0")
    return raw_value


def resolve_window_start_index(
    *,
    request: WorkflowNodeExecutionRequest,
    file_records: list[dict[str, object]],
    node_name: str,
) -> dict[str, object]:
    """解析批次窗口起点，优先使用 cursor，再回退到 start_index。"""

    cursor_payload = request.input_values.get("cursor")
    if cursor_payload is not None:
        cursor_value = require_value_payload(cursor_payload, field_name="cursor")["value"]
        if not isinstance(cursor_value, dict):
            raise InvalidRequestError(f"{node_name} 的 cursor.value 必须是对象")
        cursor_last_path = read_optional_cursor_path(
            cursor_value.get("last_path"),
            node_name=node_name,
        )
        cursor_next_start_index = read_optional_cursor_index(
            cursor_value.get("next_start_index"),
            node_name=node_name,
            field_name="next_start_index",
        )
        if cursor_last_path is not None:
            matched_index = find_file_record_index(
                file_records=file_records,
                target_path=cursor_last_path,
            )
            if matched_index is not None:
                return {
                    "start_index": matched_index + 1,
                    "start_source": "cursor.last_path",
                    "cursor_last_path": cursor_last_path,
                    "cursor_anchor_found": True,
                }
        if cursor_next_start_index is not None:
            return {
                "start_index": cursor_next_start_index,
                "start_source": "cursor.next_start_index",
                "cursor_last_path": cursor_last_path,
                "cursor_anchor_found": (
                    False if cursor_last_path is not None else None
                ),
            }
        if cursor_last_path is not None:
            return {
                "start_index": len(file_records),
                "start_source": "cursor.last_path.missing",
                "cursor_last_path": cursor_last_path,
                "cursor_anchor_found": False,
            }
        raise InvalidRequestError(
            f"{node_name} 的 cursor 至少需要 last_path 或 next_start_index 之一"
        )
    if request.input_values.get("start_index") is not None:
        return {
            "start_index": read_start_index(
                input_payload=request.input_values.get("start_index"),
                parameter_value=request.parameters.get("start_index"),
                node_name=node_name,
            ),
            "start_source": "runtime.start_index",
            "cursor_last_path": None,
            "cursor_anchor_found": None,
        }
    return {
        "start_index": read_start_index(
            input_payload=request.input_values.get("start_index"),
            parameter_value=request.parameters.get("start_index"),
            node_name=node_name,
        ),
        "start_source": "parameter.start_index",
        "cursor_last_path": None,
        "cursor_anchor_found": None,
    }


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


def find_file_record_index(
    *,
    file_records: list[dict[str, object]],
    target_path: str,
) -> int | None:
    """在当前文件记录列表中查找 cursor 锚点路径。"""

    normalized_target_path = str(
        Path(target_path).expanduser().resolve()
    ).strip().lower()
    for record_index, record in enumerate(file_records):
        current_path = str(record.get("path") or "").strip().lower()
        if current_path == normalized_target_path:
            return record_index
    return None


def read_optional_cursor_path(raw_value: object, *, node_name: str) -> str | None:
    """读取可选 cursor.last_path。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 cursor.last_path 必须是非空字符串")
    return str(Path(raw_value.strip()).expanduser().resolve())


def read_optional_cursor_index(
    raw_value: object,
    *,
    node_name: str,
    field_name: str,
) -> int | None:
    """读取可选 cursor 索引字段。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 cursor.{field_name} 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{node_name} 的 cursor.{field_name} 不能小于 0")
    return int(raw_value)


def read_runtime_scalar(
    input_payload: object,
    *,
    field_name: str,
    node_name: str,
) -> object:
    """读取可选的运行时 value.v1 标量输入。"""

    if input_payload is None:
        return None
    try:
        return require_value_payload(input_payload, field_name=field_name)["value"]
    except InvalidRequestError as exc:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 输入必须是 value.v1",
            details=getattr(exc, "details", None),
        ) from exc
