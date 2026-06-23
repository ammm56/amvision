"""value 字段提取逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, extract_value_by_path, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _value_field_extract_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按点分路径从 value.v1 中提取子字段。"""

    value_root = require_value_payload(request.input_values.get("value"), field_name="value")["value"]
    raw_path = request.parameters.get("path")
    if raw_path == "":
        extracted_value = value_root
    else:
        extracted_value = extract_value_by_path(root=value_root, path=_require_path_parameter(raw_path))
    return {"value": build_value_payload(extracted_value)}


def _require_path_parameter(raw_value: object) -> str:
    """读取非空路径参数。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("value-field-extract 的 path 必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.value-field-extract",
        display_name="Extract Value Field",
        category="logic.transform",
        description="按点分路径从 value.v1 中提取字段；path 为空字符串时直接透传整块 value。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "title": "Path",
                    "description": "点分字段路径；例如 items.0.track_id。留空字符串时直接透传整个 value。",
                },
            },
            "required": ["path"],
        },
        capability_tags=("logic.transform", "field.extract"),
    ),
    handler=_value_field_extract_handler,
)
