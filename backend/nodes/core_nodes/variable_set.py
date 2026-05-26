"""workflow 变量写入逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.nodes.core_nodes._state_node_support import require_workflow_variable_name, write_workflow_variable
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _variable_set_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把输入值或参数值写入 workflow 变量存储。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：写入后的 value payload。
    """

    variable_name = require_workflow_variable_name(request.parameters.get("name"))
    input_payload = request.input_values.get("value")
    if input_payload is not None:
        variable_value = require_value_payload(input_payload, field_name="value")["value"]
    else:
        if "value" not in request.parameters:
            raise InvalidRequestError(
                "variable.set 节点要求提供 value 输入或 value 参数",
                details={"node_id": request.node_id},
            )
        variable_value = build_value_payload(request.parameters.get("value"))["value"]
    stored_value = write_workflow_variable(
        request.execution_metadata,
        name=variable_name,
        value=variable_value,
    )
    return {"value": build_value_payload(stored_value)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.variable.set",
        display_name="Set Variable",
        category="logic.variable",
        description="把一个 value payload 或参数常量写入当前 workflow 执行级变量存储。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
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
                "name": {"type": "string"},
                "value": {},
            },
            "required": ["name"],
        },
        capability_tags=("logic.variable", "state.write"),
    ),
    handler=_variable_set_handler,
)