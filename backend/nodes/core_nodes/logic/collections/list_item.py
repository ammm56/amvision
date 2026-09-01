"""显式列表项节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.nodes.core_nodes.support.structure_items import build_list_item_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _list_item_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把显式 index 与 value 组合成 list-item.v1。"""

    value_payload = require_value_payload(
        request.input_values.get("value"),
        field_name="value",
    )
    return {
        "item": build_list_item_payload(
            index=request.parameters.get("index"),
            value=value_payload["value"],
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-item",
        display_name="List Item",
        category="core.logic.collection",
        description="把非负 index 与值显式绑定成 list-item.v1，列表顺序不再依赖连线数组顺序。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="index",
                display_name="Index",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="item",
                display_name="Item",
                payload_type_id="list-item.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "minimum": 0,
                    "title": "Index",
                    "description": "列表中的明确位置，从 0 开始。可使用固定数值，也可以连接 value.v1 动态提供。",
                },
            },
            "required": ["index"],
            "additionalProperties": False,
        },
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="index",
                input_port_name="index",
            ),
        ),
        capability_tags=("logic.structure", "value.list.item"),
        metadata={"title_parameter": "index"},
    ),
    handler=_list_item_handler,
)
