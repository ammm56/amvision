"""集合全量命中逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import coerce_truthy_bool, require_list_value
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _collection_all_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """判断数组中的全部元素是否都为 truthy。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：全量命中结果的 boolean payload。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    return {"result": build_boolean_payload(all(coerce_truthy_bool(item) for item in items_value))}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.all",
        display_name="All",
        category="logic.collection",
        description="按 truthy 语义判断数组中的全部元素是否都命中。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
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
        capability_tags=("logic.collection", "list.all"),
    ),
    handler=_collection_all_handler,
)