"""列表追加逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _list_append_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把单个值追加到列表末尾。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：追加后的列表 value payload。
    """

    items_value = require_value_payload(request.input_values.get("items"), field_name="items")["value"]
    if not isinstance(items_value, list):
        raise InvalidRequestError(
            "list-append 节点要求 items.value 必须是数组",
            details={"node_id": request.node_id},
        )
    item_value = require_value_payload(request.input_values.get("item"), field_name="item")["value"]
    return {"value": build_value_payload([*items_value, item_value])}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-append",
        display_name="Append List Item",
        category="logic.collection",
        description="把一个 value payload 中的值追加到列表末尾，并返回新的列表。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="item",
                display_name="Item",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("logic.collection", "list.append"),
    ),
    handler=_list_append_handler,
)