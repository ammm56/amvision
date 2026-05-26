"""布尔非逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, require_boolean_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _boolean_not_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入布尔值执行逻辑非。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：逻辑非之后的 boolean payload。
    """

    condition = require_boolean_payload(request.input_values.get("condition"), field_name="condition")
    return {"result": build_boolean_payload(not condition["value"])}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.boolean-not",
        display_name="Boolean Not",
        category="logic.boolean",
        description="对输入布尔值执行逻辑非。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="condition",
                display_name="Condition",
                payload_type_id="boolean.v1",
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
        capability_tags=("logic.boolean", "condition.negate"),
    ),
    handler=_boolean_not_handler,
)