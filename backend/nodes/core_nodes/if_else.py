"""最小 if else 选择节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_boolean_payload, require_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _if_else_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据布尔条件在两个输入值之间选择其一。"""

    condition = require_boolean_payload(request.input_values.get("condition"), field_name="condition")
    true_value = require_value_payload(request.input_values.get("if_true"), field_name="if_true")
    false_value = require_value_payload(request.input_values.get("if_false"), field_name="if_false")
    selected_value = true_value["value"] if condition["value"] is True else false_value["value"]
    return {"value": build_value_payload(selected_value)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.if-else",
        display_name="If Else Select",
        category="logic.branch",
        description="根据条件在 if_true 和 if_false 两个值之间做最小选择。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="condition",
                display_name="Condition",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="if_true",
                display_name="If True",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="if_false",
                display_name="If False",
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
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("logic.branch", "condition.select"),
    ),
    handler=_if_else_handler,
)