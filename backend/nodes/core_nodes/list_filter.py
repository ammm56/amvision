"""列表过滤逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import require_list_value
from backend.nodes.core_nodes._condition_expression_support import (
    evaluate_condition_expression,
    require_condition_expression,
)
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _list_filter_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按条件表达式过滤列表项。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：过滤后的列表与命中数量。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    condition = _resolve_filter_condition(request)
    filtered_items: list[object] = []
    for item_index, item_value in enumerate(items_value):
        if evaluate_condition_expression(
            root_value=item_value,
            condition=condition,
            node_id=request.node_id,
            context_label=f"items[{item_index}]",
        ):
            filtered_items.append(item_value)
    return {
        "value": build_value_payload(filtered_items),
        "count": build_value_payload(len(filtered_items)),
    }


def _resolve_filter_condition(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """读取并校验 list-filter 的条件表达式。"""

    input_payload = request.input_values.get("condition")
    if input_payload is not None:
        raw_condition = require_value_payload(input_payload, field_name="condition")["value"]
    else:
        if "condition" not in request.parameters:
            raise InvalidRequestError(
                "list-filter 节点要求提供 condition 输入或 condition 参数",
                details={"node_id": request.node_id},
            )
        raw_condition = request.parameters.get("condition")
    return require_condition_expression(raw_condition, node_id=request.node_id, context_label="filter")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-filter",
        display_name="Filter List",
        category="logic.collection",
        description="按条件表达式过滤列表项，条件 DSL 与 match-case 保持一致。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="condition",
                display_name="Condition",
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
            NodePortDefinition(
                name="count",
                display_name="Count",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "condition": {
                    "type": "object",
                },
            },
        },
        capability_tags=("logic.collection", "list.filter"),
    ),
    handler=_list_filter_handler,
)