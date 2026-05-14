"""workflow 变量删除逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._state_node_support import delete_workflow_variable, require_workflow_variable_name
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _variable_delete_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """删除 workflow 变量并返回删除前状态。"""

    variable_name = require_workflow_variable_name(request.parameters.get("name"))
    existed, deleted_value = delete_workflow_variable(request.execution_metadata, name=variable_name)
    return {
        "value": build_value_payload(deleted_value),
        "existed": build_boolean_payload(existed),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.variable.delete",
        display_name="Delete Variable",
        category="logic.variable",
        description="删除当前 workflow 执行级变量，并返回删除前的值与存在状态。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="existed",
                display_name="Existed",
                payload_type_id="boolean.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        capability_tags=("logic.variable", "state.delete"),
    ),
    handler=_variable_delete_handler,
)