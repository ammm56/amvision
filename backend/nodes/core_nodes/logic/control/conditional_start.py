"""真正控制图执行路径的 Conditional 起点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    require_boolean_payload,
    require_value_payload,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _conditional_start_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """计算选中分支，实际分支节点由 Graph Executor 执行。"""

    condition = require_boolean_payload(
        request.input_values.get("condition"),
        field_name="condition",
    )["value"]
    raw_value = request.input_values.get("value")
    value_payload = (
        require_value_payload(raw_value, field_name="value")
        if raw_value is not None
        else build_value_payload(None)
    )
    selected_branch = "if_true" if condition is True else "if_false"
    return {
        "if_true": value_payload,
        "if_false": value_payload,
        "selected_branch": build_value_payload(selected_branch),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.conditional-start",
        display_name="Conditional Start",
        category="core.logic.branch",
        description="按 Condition 只执行 If True 或 If False 分支，未选分支不会运行。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="condition",
                display_name="Condition",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
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
            NodePortDefinition(
                name="selected_branch",
                display_name="Selected Branch",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=(
            "logic.branch",
            "conditional.boundary.start",
            "execution.control-flow",
        ),
    ),
    handler=_conditional_start_handler,
)
