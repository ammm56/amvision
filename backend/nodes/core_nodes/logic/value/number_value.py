"""通用数值常量节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.logic.numeric._common import require_finite_number
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把显式有限数值参数包装为标准 value.v1。"""

    value = require_finite_number(request.parameters.get("value", 0), field_name="value")
    return {"value": build_value_payload(value)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.number-value",
        display_name="Number Value",
        category="core.logic.value",
        description="输出一个明确配置的有限数值 value.v1，供通用参数端口复用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
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
                "value": {
                    "type": "number",
                    "default": 0,
                    "title": "Value",
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("logic.value", "value.constant", "execution.pure"),
    ),
    handler=_handler,
)
