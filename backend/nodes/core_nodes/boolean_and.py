"""布尔与逻辑节点。"""

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


def _boolean_and_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对两个布尔值执行逻辑与。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：逻辑与之后的 boolean payload。
    """

    left_value = require_boolean_payload(request.input_values.get("left"), field_name="left")
    right_value = require_boolean_payload(request.input_values.get("right"), field_name="right")
    return {"result": build_boolean_payload(left_value["value"] and right_value["value"])}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.boolean-and",
        display_name="Boolean And",
        category="logic.boolean",
        description="对两个输入布尔值执行逻辑与。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="left",
                display_name="Left",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="right",
                display_name="Right",
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
        capability_tags=("logic.boolean", "condition.and"),
    ),
    handler=_boolean_and_handler,
)