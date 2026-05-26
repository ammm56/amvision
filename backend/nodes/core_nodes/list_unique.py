"""列表去重逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import build_collection_identity_key, require_list_value
from backend.nodes.core_nodes._logic_node_support import build_value_payload, try_extract_value_by_path
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _list_unique_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按完整值或指定 path 对列表稳定去重。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：去重后的列表和数量。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    path = _read_optional_unique_path(request.parameters.get("path"))
    seen_keys: set[str] = set()
    unique_items: list[object] = []
    for item_index, item_value in enumerate(items_value):
        unique_key = _build_unique_key(item_value=item_value, path=path, node_id=request.node_id, item_index=item_index)
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        unique_items.append(item_value)
    return {
        "value": build_value_payload(unique_items),
        "count": build_value_payload(len(unique_items)),
    }


def _build_unique_key(*, item_value: object, path: str | None, node_id: str, item_index: int) -> str:
    """构造单个列表项的去重 key。"""

    if path is None:
        return build_collection_identity_key(item_value)
    exists, extracted_value = try_extract_value_by_path(root=item_value, path=path)
    if not exists:
        raise InvalidRequestError(
            "list-unique 节点无法从列表项提取指定 path",
            details={"node_id": node_id, "item_index": item_index, "path": path},
        )
    return build_collection_identity_key(extracted_value)


def _read_optional_unique_path(raw_value: object) -> str | None:
    """读取 list-unique 的可选去重路径。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("list-unique 节点的 path 必须是非空字符串")
    return raw_value.strip()


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-unique",
        display_name="Unique List",
        category="logic.collection",
        description="按完整值或指定 path 对列表稳定去重，适合 workflow app 的声明式清洗。",
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
        capability_tags=("logic.collection", "list.unique"),
    ),
    handler=_list_unique_handler,
)