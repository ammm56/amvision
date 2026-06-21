"""字段提取逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, extract_value_by_path
from backend.nodes.core_nodes._service_node_support import require_str_parameter
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _field_extract_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从 response-body 输入中提取指定字段。"""

    body_payload = request.input_values.get("body")
    raw_path = request.parameters.get("path")
    if raw_path == "":
        extracted_value = body_payload
    else:
        extracted_value = extract_value_by_path(
            root=body_payload,
            path=require_str_parameter(request, "path"),
        )
    return {"value": build_value_payload(extracted_value)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.field-extract",
        display_name="Extract Field",
        category="logic.transform",
        description="按点分路径从 response-body 中提取字段；path 为空字符串时直接透传整块 body。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
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
                    "description": "点分字段路径；例如 image.image_base64 或 result.items.0.class_name。留空字符串时直接透传整个 body，适合先把 response-body 转成 value.v1 再交给 object-create 或 value-preview。",
                },
            },
            "required": ["path"],
        },
        capability_tags=("logic.transform", "field.extract"),
    ),
    handler=_field_extract_handler,
)
