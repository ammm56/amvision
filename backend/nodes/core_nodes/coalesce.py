"""值回退逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _coalesce_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """返回多个候选值中的第一个非 null 值。"""

    primary_payload = request.input_values.get("primary")
    if primary_payload is not None:
        primary_value = require_value_payload(primary_payload, field_name="primary")["value"]
        if primary_value is not None:
            return {"value": build_value_payload(primary_value)}

    fallback_payload = request.input_values.get("fallback")
    if fallback_payload is not None:
        return {"value": require_value_payload(fallback_payload, field_name="fallback")}

    if "fallback_value" in request.parameters:
        return {"value": build_value_payload(request.parameters.get("fallback_value"))}

    return {"value": build_value_payload(None)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.coalesce",
        display_name="Coalesce",
        category="logic.value",
        description="返回 primary、fallback、fallback_value 中的第一个非 null 值。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="primary",
                display_name="Primary",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="fallback",
                display_name="Fallback",
                payload_type_id="value.v1",
                required=False,
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
                "fallback_value": {},
            },
        },
        capability_tags=("logic.value", "value.coalesce"),
    ),
    handler=_coalesce_handler,
)