"""text.v1 转 value.v1 节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_text_payload
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把文本正文包装为 value.v1。"""

    payload = require_text_payload(request.input_values.get("text"))
    return {"value": build_value_payload(payload["text"])}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.text-to-value",
        display_name="Text To Value",
        category="core.logic.value",
        description="把 text.v1 的正文转换为 value.v1 字符串。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="text", display_name="Text", payload_type_id="text.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value", display_name="Value", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        capability_tags=("logic.convert",),
    ),
    handler=_handler,
)
