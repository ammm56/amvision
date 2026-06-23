"""目录游标输入解析 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


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
