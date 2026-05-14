"""列表分组逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import require_list_value, stringify_group_key
from backend.nodes.core_nodes._logic_node_support import build_value_payload, try_extract_value_by_path
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _list_group_by_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按标量值或 path 对列表项分组。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：分组对象、分组 key 列表和分组数量。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    path = _read_optional_group_path(request.parameters.get("path"))
    grouped_items: dict[str, list[object]] = {}
    grouped_keys: list[str] = []
    for item_index, item_value in enumerate(items_value):
        group_value = _read_group_value(item_value=item_value, path=path, node_id=request.node_id, item_index=item_index)
        group_key = stringify_group_key(group_value, node_id=request.node_id, field_name="group_key")
        if group_key not in grouped_items:
            grouped_items[group_key] = []
            grouped_keys.append(group_key)
        grouped_items[group_key].append(item_value)
    return {
        "value": build_value_payload(grouped_items),
        "keys": build_value_payload(grouped_keys),
        "count": build_value_payload(len(grouped_keys)),
    }


def _read_group_value(*, item_value: object, path: str | None, node_id: str, item_index: int) -> object:
    """读取单个列表项的分组 key 原值。"""

    if path is None:
        return item_value
    exists, extracted_value = try_extract_value_by_path(root=item_value, path=path)
    if not exists:
        raise InvalidRequestError(
            "list-group-by 节点无法从列表项提取指定 path",
            details={"node_id": node_id, "item_index": item_index, "path": path},
        )
    return extracted_value


def _read_optional_group_path(raw_value: object) -> str | None:
    """读取 list-group-by 的可选分组路径。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("list-group-by 节点的 path 必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-group-by",
        display_name="Group List",
        category="logic.collection",
        description="按标量值或指定 path 对列表项分组，输出分组对象、分组 key 列表和数量。",
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
            NodePortDefinition(
                name="keys",
                display_name="Keys",
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
                "path": {"type": "string"},
            },
        },
        capability_tags=("logic.collection", "list.group-by"),
    ),
    handler=_list_group_by_handler,
)