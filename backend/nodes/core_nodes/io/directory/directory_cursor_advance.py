"""目录游标推进节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.directory_cursor import (
    normalize_cursor_mapping,
    read_cursor_object_input,
)
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "directory-cursor-advance"


def _directory_cursor_advance_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """根据目录窗口输出推进下一步 cursor。"""

    allow_regress = _read_allow_regress(request.parameters.get("allow_regress"))
    preserve_extra_fields = _read_preserve_extra_fields(
        request.parameters.get("preserve_extra_fields")
    )

    previous_cursor = _read_optional_previous_cursor(
        request,
        preserve_extra_fields=preserve_extra_fields,
    )
    window_cursor, window_source = _read_required_window_cursor(
        request,
        preserve_extra_fields=preserve_extra_fields,
    )

    previous_next_start_index = int(previous_cursor["next_start_index"]) if previous_cursor is not None else 0
    current_next_start_index = int(window_cursor["next_start_index"])
    regressed = previous_cursor is not None and current_next_start_index < previous_next_start_index
    if regressed and not allow_regress:
        raise InvalidRequestError(
            "directory-cursor-advance 当前不允许 next_start_index 回退",
            details={
                "previous_next_start_index": previous_next_start_index,
                "current_next_start_index": current_next_start_index,
            },
        )

    advanced = _compute_advanced(previous_cursor=previous_cursor, current_cursor=window_cursor)
    advanced_count = _compute_advanced_count(
        previous_cursor=previous_cursor,
        current_cursor=window_cursor,
    )
    merged_cursor = dict(previous_cursor or {})
    merged_cursor.update(window_cursor)
    return {
        "cursor": build_value_payload(merged_cursor),
        "summary": build_value_payload(
            {
                "window_source": window_source,
                "allow_regress": allow_regress,
                "preserve_extra_fields": preserve_extra_fields,
                "advanced": advanced,
                "advanced_count": advanced_count,
                "regressed": regressed,
                "previous_last_path": previous_cursor.get("last_path") if previous_cursor is not None else None,
                "previous_next_start_index": previous_next_start_index if previous_cursor is not None else None,
                "current_last_path": merged_cursor.get("last_path"),
                "current_next_start_index": current_next_start_index,
                "completed": bool(merged_cursor["completed"]),
                "has_work": bool(merged_cursor["has_work"]),
                "no_work_reason": merged_cursor.get("no_work_reason"),
            }
        ),
    }


def _read_optional_previous_cursor(
    request: WorkflowNodeExecutionRequest,
    *,
    preserve_extra_fields: bool,
) -> dict[str, object] | None:
    """读取可选的上一版 cursor。"""

    raw_payload = request.input_values.get("cursor")
    if raw_payload is None:
        return None
    raw_cursor, _ = read_cursor_object_input(
        request,
        node_name=NODE_NAME,
    )
    return normalize_cursor_mapping(
        raw_cursor,
        node_name=NODE_NAME,
        preserve_extra_fields=preserve_extra_fields,
    )


def _read_required_window_cursor(
    request: WorkflowNodeExecutionRequest,
    *,
    preserve_extra_fields: bool,
) -> tuple[dict[str, object], str]:
    """读取必须提供的目录窗口 cursor。"""

    raw_window_cursor_payload = request.input_values.get("window_cursor")
    if raw_window_cursor_payload is not None:
        raw_value = require_value_payload(
            raw_window_cursor_payload,
            field_name="window_cursor",
        )["value"]
        if not isinstance(raw_value, dict):
            raise InvalidRequestError("directory-cursor-advance 的 window_cursor.value 必须是对象")
        normalized_cursor = normalize_cursor_mapping(
            raw_value,
            node_name=NODE_NAME,
            preserve_extra_fields=preserve_extra_fields,
        )
        return normalized_cursor, "input.window_cursor"
    raw_window_summary_payload = request.input_values.get("window_summary")
    if raw_window_summary_payload is None:
        raise InvalidRequestError(
            "directory-cursor-advance 需要 window_cursor 或 window_summary 输入"
        )
    raw_value = require_value_payload(
        raw_window_summary_payload,
        field_name="window_summary",
    )["value"]
    if not isinstance(raw_value, dict):
        raise InvalidRequestError("directory-cursor-advance 的 window_summary.value 必须是对象")
    normalized_cursor = normalize_cursor_mapping(
        raw_value,
        node_name=NODE_NAME,
        preserve_extra_fields=preserve_extra_fields,
    )
    return normalized_cursor, "input.window_summary"


def _compute_advanced(
    *,
    previous_cursor: dict[str, object] | None,
    current_cursor: dict[str, object],
) -> bool:
    """判断当前 cursor 是否真正推进。"""

    if previous_cursor is None:
        return bool(current_cursor["has_work"]) or int(current_cursor["next_start_index"]) > 0
    if current_cursor.get("last_path") != previous_cursor.get("last_path"):
        return True
    return int(current_cursor["next_start_index"]) != int(previous_cursor["next_start_index"])


def _compute_advanced_count(
    *,
    previous_cursor: dict[str, object] | None,
    current_cursor: dict[str, object],
) -> int:
    """计算本次推进的数量。"""

    if previous_cursor is None:
        return int(current_cursor["count"])
    return max(
        int(current_cursor["next_start_index"]) - int(previous_cursor["next_start_index"]),
        0,
    )


def _read_allow_regress(raw_value: object) -> bool:
    """读取是否允许回退。"""

    if raw_value is None:
        return False
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("directory-cursor-advance 的 allow_regress 必须是布尔值")
    return raw_value


def _read_preserve_extra_fields(raw_value: object) -> bool:
    """读取是否保留额外字段。"""

    if raw_value is None:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("directory-cursor-advance 的 preserve_extra_fields 必须是布尔值")
    return raw_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.directory-cursor-advance",
        display_name="Directory Cursor Advance",
        category="io.input",
        description="根据 directory-batch-window 或 directory-poll-window 的输出 cursor，统一推进下一步目录游标。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="cursor",
                display_name="Cursor",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="window_cursor",
                display_name="Window Cursor",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="window_summary",
                display_name="Window Summary",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="cursor",
                display_name="Cursor",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "allow_regress": {
                    "type": "boolean",
                    "title": "允许游标回退",
                    "default": False,
                },
                "preserve_extra_fields": {
                    "type": "boolean",
                    "title": "保留额外字段",
                    "default": True,
                },
            },
        },
        capability_tags=("io.input", "filesystem.cursor", "inspection.batch-input"),
    ),
    handler=_directory_cursor_advance_handler,
)
