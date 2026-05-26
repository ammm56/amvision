"""列表排序逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import require_list_value
from backend.nodes.core_nodes._logic_node_support import build_value_payload, try_extract_value_by_path
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _list_sort_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按标量值或 path 对列表稳定排序。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：排序后的列表 value payload。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    path = _read_optional_sort_path(request.parameters.get("path"))
    descending = _read_optional_bool(request.parameters.get("descending"), default=False)
    sortable_items = [
        (_read_sort_key(item_value=item_value, path=path, node_id=request.node_id, item_index=item_index), item_value)
        for item_index, item_value in enumerate(items_value)
    ]
    _validate_sort_key_types(sortable_items, node_id=request.node_id)
    sorted_items = [
        item_value
        for _, item_value in sorted(
            sortable_items,
            key=lambda pair: pair[0],
            reverse=descending,
        )
    ]
    return {"value": build_value_payload(sorted_items)}


def _read_sort_key(*, item_value: object, path: str | None, node_id: str, item_index: int) -> object:
    """读取单个列表项的排序 key。"""

    if path is None:
        return _require_sortable_value(item_value, node_id=node_id, item_index=item_index, path=None)
    exists, extracted_value = try_extract_value_by_path(root=item_value, path=path)
    if not exists:
        raise InvalidRequestError(
            "list-sort 节点无法从列表项提取指定 path",
            details={"node_id": node_id, "item_index": item_index, "path": path},
        )
    return _require_sortable_value(extracted_value, node_id=node_id, item_index=item_index, path=path)


def _require_sortable_value(value: object, *, node_id: str, item_index: int, path: str | None) -> object:
    """校验排序 key 只支持数字或字符串。"""

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InvalidRequestError(
            "list-sort 节点的排序 key 只支持数字或字符串",
            details={
                "node_id": node_id,
                "item_index": item_index,
                "path": path,
                "value_type": value.__class__.__name__,
            },
        )
    return value


def _validate_sort_key_types(sortable_items: list[tuple[object, object]], *, node_id: str) -> None:
    """校验所有排序 key 的类型一致。"""

    if not sortable_items:
        return
    first_key = sortable_items[0][0]
    expect_string = isinstance(first_key, str)
    for item_index, (sort_key, _) in enumerate(sortable_items[1:], start=1):
        if expect_string != isinstance(sort_key, str):
            raise InvalidRequestError(
                "list-sort 节点要求全部排序 key 必须是同类数字或字符串",
                details={"node_id": node_id, "item_index": item_index},
            )


def _read_optional_sort_path(raw_value: object) -> str | None:
    """读取 list-sort 的可选排序路径。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("list-sort 节点的 path 必须是非空字符串")
    return raw_value.strip()


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError("descending 必须是布尔值")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-sort",
        display_name="Sort List",
        category="logic.collection",
        description="按标量值或指定 path 对列表稳定排序，适合 workflow app 的声明式重排。",
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
                "path": {"type": "string"},
                "descending": {"type": "boolean"},
            },
        },
        capability_tags=("logic.collection", "list.sort"),
    ),
    handler=_list_sort_handler,
)