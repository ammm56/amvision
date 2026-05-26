"""集合归约逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import require_list_value
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _collection_reduce_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按指定 operator 对数组执行归约。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：归约后的 value payload。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    operator = _require_reduce_operator(request.parameters.get("operator"))
    if operator == "sum":
        return {"value": build_value_payload(_reduce_sum(items_value, node_id=request.node_id))}
    if operator == "join":
        separator = _read_join_separator(request.parameters.get("separator"))
        return {"value": build_value_payload(_reduce_join(items_value, separator=separator, node_id=request.node_id))}
    if operator == "min":
        return {"value": build_value_payload(_reduce_ordered(items_value, node_id=request.node_id, operator="min"))}
    if operator == "max":
        return {"value": build_value_payload(_reduce_ordered(items_value, node_id=request.node_id, operator="max"))}
    if operator == "first":
        return {"value": build_value_payload(_reduce_edge_item(items_value, node_id=request.node_id, operator="first"))}
    if operator == "last":
        return {"value": build_value_payload(_reduce_edge_item(items_value, node_id=request.node_id, operator="last"))}
    raise InvalidRequestError(
        "reduce 节点不支持指定 operator",
        details={"node_id": request.node_id, "operator": operator},
    )


def _require_reduce_operator(raw_value: object) -> str:
    """读取并校验 reduce operator。

    参数：
    - raw_value：待校验的原始参数值。

    返回：
    - str：规范化后的 operator。
    """

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("reduce 节点要求 operator 必须是非空字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"sum", "join", "min", "max", "first", "last"}:
        raise InvalidRequestError(
            "reduce 节点不支持指定 operator",
            details={"operator": raw_value},
        )
    return normalized_value


def _read_join_separator(raw_value: object) -> str:
    """读取 join 操作的分隔符参数。

    参数：
    - raw_value：待校验的原始参数值。

    返回：
    - str：join 使用的分隔符。
    """

    if raw_value is None:
        return ""
    if isinstance(raw_value, str):
        return raw_value
    raise InvalidRequestError("reduce 节点的 separator 必须是字符串")


def _reduce_sum(items_value: list[object], *, node_id: str) -> int | float:
    """对数字数组执行求和。"""

    total: int | float = 0
    for item_value in items_value:
        if isinstance(item_value, bool) or not isinstance(item_value, (int, float)):
            raise InvalidRequestError(
                "reduce 节点的 sum 只支持数字数组",
                details={"node_id": node_id, "item_value": item_value},
            )
        total += item_value
    return total


def _reduce_join(items_value: list[object], *, separator: str, node_id: str) -> str:
    """对字符串数组执行拼接。"""

    normalized_items: list[str] = []
    for item_value in items_value:
        if not isinstance(item_value, str):
            raise InvalidRequestError(
                "reduce 节点的 join 只支持字符串数组",
                details={"node_id": node_id, "item_value": item_value},
            )
        normalized_items.append(item_value)
    return separator.join(normalized_items)


def _reduce_ordered(items_value: list[object], *, node_id: str, operator: str) -> object:
    """对有序数组执行最小值或最大值归约。"""

    if not items_value:
        raise InvalidRequestError(
            "reduce 节点的 min/max 在空数组上至少需要一个元素",
            details={"node_id": node_id, "operator": operator},
        )
    first_item = items_value[0]
    if isinstance(first_item, bool):
        raise InvalidRequestError(
            "reduce 节点的 min/max 不支持布尔值数组",
            details={"node_id": node_id, "operator": operator},
        )
    if isinstance(first_item, (int, float)):
        if any(isinstance(item_value, bool) or not isinstance(item_value, (int, float)) for item_value in items_value[1:]):
            raise InvalidRequestError(
                "reduce 节点的 min/max 只支持同类数字或字符串数组",
                details={"node_id": node_id, "operator": operator},
            )
        return min(items_value) if operator == "min" else max(items_value)
    if isinstance(first_item, str):
        if any(not isinstance(item_value, str) for item_value in items_value[1:]):
            raise InvalidRequestError(
                "reduce 节点的 min/max 只支持同类数字或字符串数组",
                details={"node_id": node_id, "operator": operator},
            )
        return min(items_value) if operator == "min" else max(items_value)
    raise InvalidRequestError(
        "reduce 节点的 min/max 只支持同类数字或字符串数组",
        details={
            "node_id": node_id,
            "operator": operator,
            "item_type": first_item.__class__.__name__,
        },
    )


def _reduce_edge_item(items_value: list[object], *, node_id: str, operator: str) -> object:
    """返回数组的第一个或最后一个元素。"""

    if not items_value:
        raise InvalidRequestError(
            "reduce 节点的 first/last 在空数组上至少需要一个元素",
            details={"node_id": node_id, "operator": operator},
        )
    return items_value[0] if operator == "first" else items_value[-1]


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.reduce",
        display_name="Reduce",
        category="logic.collection",
        description="按指定 operator 对数组执行最小归约，支持 sum、join、min、max、first、last。",
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
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "operator": {
                    "type": "string",
                    "enum": ["sum", "join", "min", "max", "first", "last"],
                },
                "separator": {"type": "string"},
            },
            "required": ["operator"],
        },
        capability_tags=("logic.collection", "list.reduce"),
    ),
    handler=_collection_reduce_handler,
)