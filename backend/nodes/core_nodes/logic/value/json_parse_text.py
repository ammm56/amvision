"""JSON 文本解析节点。"""

from __future__ import annotations

import json

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_text_payload
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """显式解析 text.v1 正文中的 JSON 值。"""

    payload = require_text_payload(request.input_values.get("text"))
    try:
        value = json.loads(str(payload["text"]))
    except json.JSONDecodeError as exc:
        raise InvalidRequestError(
            "JSON Parse Text 收到的正文不是有效 JSON",
            details={"line": exc.lineno, "column": exc.colno},
        ) from exc
    return {"value": build_value_payload(value)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.json-parse-text",
        display_name="JSON Parse Text",
        category="core.logic.value",
        description="把 text.v1 正文显式解析为任意 JSON value.v1。",
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
        capability_tags=("logic.json", "logic.convert"),
    ),
    handler=_handler,
)
