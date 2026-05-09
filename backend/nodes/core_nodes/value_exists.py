"""值存在性判断逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, require_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _value_exists_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """判断 value payload 中的值是否为非 null。"""

    value_payload = require_value_payload(request.input_values.get("value"), field_name="value")
    return {"result": build_boolean_payload(value_payload["value"] is not None)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.value-exists",
        display_name="Value Exists",
        category="logic.value",
        description="判断输入 value payload 中的值是否为非 null。",
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
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("logic.value", "value.exists"),
    ),
    handler=_value_exists_handler,
)