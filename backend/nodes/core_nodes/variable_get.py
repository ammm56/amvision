"""workflow 变量读取逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.nodes.core_nodes._state_node_support import read_workflow_variable, require_workflow_variable_name
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _variable_get_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从 workflow 变量存储中读取指定变量。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：读取到的 value payload。
    """

    variable_name = require_workflow_variable_name(request.parameters.get("name"))
    exists, variable_value = read_workflow_variable(
        request.execution_metadata,
        name=variable_name,
    )
    if exists:
        return {"value": build_value_payload(variable_value)}

    default_input_payload = request.input_values.get("default")
    if default_input_payload is not None:
        return {"value": require_value_payload(default_input_payload, field_name="default")}
    if "default_value" in request.parameters:
        return {"value": build_value_payload(request.parameters.get("default_value"))}
    raise InvalidRequestError(
        "variable.get 节点读取的变量不存在，且未提供默认值",
        details={"node_id": request.node_id, "name": variable_name},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.variable.get",
        display_name="Get Variable",
        category="logic.variable",
        description="从当前 workflow 执行级变量存储读取一个值，并在缺失时支持默认值回退。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="default",
                display_name="Default",
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
                "default_value": {},
            },
            "required": ["name"],
        },
        capability_tags=("logic.variable", "state.read"),
    ),
    handler=_variable_get_handler,
)