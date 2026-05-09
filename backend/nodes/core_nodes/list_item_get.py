"""列表项读取逻辑节点。"""

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


def _list_item_get_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按索引读取列表中的单个元素。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：读取到的 value payload。
    """

    items_value = require_value_payload(request.input_values.get("items"), field_name="items")["value"]
    if not isinstance(items_value, list):
        raise InvalidRequestError(
            "list-item-get 节点要求 items.value 必须是数组",
            details={"node_id": request.node_id},
        )
    resolved_index = _resolve_index(request)
    allow_negative = _read_optional_bool(request.parameters.get("allow_negative"), default=True)
    normalized_index = resolved_index
    if normalized_index < 0 and allow_negative:
        normalized_index += len(items_value)
    if 0 <= normalized_index < len(items_value):
        return {"value": build_value_payload(items_value[normalized_index])}
    if "default_value" in request.parameters:
        return {"value": build_value_payload(request.parameters.get("default_value"))}
    raise InvalidRequestError(
        "list-item-get 节点索引越界",
        details={
            "node_id": request.node_id,
            "index": resolved_index,
            "normalized_index": normalized_index,
            "size": len(items_value),
        },
    )


def _resolve_index(request: WorkflowNodeExecutionRequest) -> int:
    """从输入端口或节点参数解析索引值。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - int：解析后的索引。
    """

    index_payload = request.input_values.get("index")
    if index_payload is not None:
        raw_index = require_value_payload(index_payload, field_name="index")["value"]
    else:
        if "index" not in request.parameters:
            raise InvalidRequestError(
                "list-item-get 节点要求提供 index 输入或 index 参数",
                details={"node_id": request.node_id},
            )
        raw_index = request.parameters.get("index")
    if isinstance(raw_index, bool) or not isinstance(raw_index, int):
        raise InvalidRequestError(
            "list-item-get 节点要求 index 必须是整数",
            details={"node_id": request.node_id, "index": raw_index},
        )
    return raw_index


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError("allow_negative 必须是布尔值")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-item-get",
        display_name="Get List Item",
        category="logic.collection",
        description="按索引从 value payload 中的列表读取一个元素，支持负索引与默认值回退。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
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
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "allow_negative": {"type": "boolean"},
                "default_value": {},
            },
        },
        capability_tags=("logic.collection", "list.read"),
    ),
    handler=_list_item_get_handler,
)