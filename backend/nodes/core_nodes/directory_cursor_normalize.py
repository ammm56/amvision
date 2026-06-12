"""目录游标规范化节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._directory_cursor_node_support import (
    normalize_cursor_mapping,
    read_cursor_object_input,
)
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


NODE_NAME = "directory-cursor-normalize"


def _directory_cursor_normalize_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把目录游标对象规整为稳定结构。"""

    default_batch_size = _read_default_batch_size(request.parameters.get("default_batch_size"))
    preserve_extra_fields = _read_preserve_extra_fields(
        request.parameters.get("preserve_extra_fields")
    )
    raw_cursor, source = read_cursor_object_input(
        request,
        default_value=request.parameters.get("default_value"),
        node_name=NODE_NAME,
    )
    normalized_cursor = normalize_cursor_mapping(
        raw_cursor,
        node_name=NODE_NAME,
        default_batch_size=default_batch_size,
        preserve_extra_fields=preserve_extra_fields,
    )
    return {
        "cursor": build_value_payload(normalized_cursor),
        "summary": build_value_payload(
            {
                "source": source,
                "default_batch_size": default_batch_size,
                "preserve_extra_fields": preserve_extra_fields,
                "field_names": list(normalized_cursor.keys()),
                "count": int(normalized_cursor["count"]),
                "next_start_index": int(normalized_cursor["next_start_index"]),
                "completed": bool(normalized_cursor["completed"]),
                "has_work": bool(normalized_cursor["has_work"]),
            }
        ),
    }


def _read_default_batch_size(raw_value: object) -> int | None:
    """读取默认批次大小。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("directory-cursor-normalize 的 default_batch_size 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError("directory-cursor-normalize 的 default_batch_size 不能小于 0")
    return int(raw_value)


def _read_preserve_extra_fields(raw_value: object) -> bool:
    """读取是否保留额外字段。"""

    if raw_value is None:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("directory-cursor-normalize 的 preserve_extra_fields 必须是布尔值")
    return raw_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.directory-cursor-normalize",
        display_name="Directory Cursor Normalize",
        category="io.input",
        description="把本地 JSON、运行时 value 或目录窗口 summary 中的 cursor 统一规整成稳定 cursor 对象。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="cursor",
                display_name="Cursor",
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
                "default_value": {
                    "type": "object",
                    "title": "默认游标对象",
                },
                "default_batch_size": {
                    "type": "integer",
                    "title": "默认批次大小",
                    "minimum": 0,
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
    handler=_directory_cursor_normalize_handler,
)
