"""真正控制图执行路径的 Switch 起点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.workflows.execution.selection import (
    MAX_SWITCH_CASES,
    normalize_switch_case_values,
    select_switch_branch_name,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _switch_start_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算命中的 case，实际分支节点由 Graph Executor 执行。"""

    selector = require_value_payload(
        request.input_values.get("selector"),
        field_name="selector",
    )["value"]
    case_values = normalize_switch_case_values(
        request.parameters.get("case_values", [1]),
        node_id=request.node_id,
    )
    selected_branch = select_switch_branch_name(selector, case_values)
    raw_value = request.input_values.get("value")
    value_payload = (
        require_value_payload(raw_value, field_name="value")
        if raw_value is not None
        else build_value_payload(None)
    )
    outputs = {
        f"case_{case_index}": value_payload
        for case_index in range(1, MAX_SWITCH_CASES + 1)
    }
    outputs["default"] = value_payload
    outputs["selected_branch"] = build_value_payload(selected_branch)
    return outputs


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.switch-start",
        display_name="Switch Start",
        category="core.logic.branch",
        description="按 1–8 个 JSON scalar case 只执行一个 case 或 Default 分支。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="selector",
                display_name="Selector",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=tuple(
            [
                *(
                    NodePortDefinition(
                        name=f"case_{case_index}",
                        display_name=f"Case {case_index}",
                        payload_type_id="value.v1",
                    )
                    for case_index in range(1, MAX_SWITCH_CASES + 1)
                ),
                NodePortDefinition(
                    name="default",
                    display_name="Default",
                    payload_type_id="value.v1",
                ),
                NodePortDefinition(
                    name="selected_branch",
                    display_name="Selected Branch",
                    payload_type_id="value.v1",
                ),
            ]
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "case_values": {
                    "type": "array",
                    "title": "Case Values",
                    "minItems": 1,
                    "maxItems": MAX_SWITCH_CASES,
                    "default": [1],
                    "description": "按数组顺序对应 Case 1–8，只支持 JSON scalar。",
                },
            },
            "required": ["case_values"],
        },
        capability_tags=(
            "logic.branch",
            "switch.boundary.start",
            "execution.control-flow",
        ),
    ),
    handler=_switch_start_handler,
)
