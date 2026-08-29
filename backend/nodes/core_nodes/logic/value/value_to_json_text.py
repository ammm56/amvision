"""value.v1 转 JSON text.v1 节点。"""

from __future__ import annotations

import json

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用稳定 UTF-8 JSON 表示生成 text.v1。"""

    value = require_value_payload(request.input_values.get("value"))["value"]
    pretty = request.parameters.get("pretty", False) is True
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    return {
        "text": {
            "text": text,
            "media_type": "application/json",
            "charset": "utf-8",
        }
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.value-to-json-text",
        display_name="Value To JSON Text",
        category="core.logic.value",
        description="把 value.v1 显式编码为稳定 UTF-8 JSON text.v1。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value", display_name="Value", payload_type_id="value.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="text", display_name="Text", payload_type_id="text.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {"pretty": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
        capability_tags=("logic.json", "logic.convert"),
    ),
    handler=_handler,
)
