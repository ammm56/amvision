"""列表映射逻辑节点。"""

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


def _list_map_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 path 逐项把列表映射为新的值列表。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：映射后的列表 value payload。
    """

    items_value = require_list_value(
        request.input_values.get("items"),
        field_name="items",
        node_id=request.node_id,
    )
    path = _read_optional_map_path(request.parameters.get("path"))
    skip_missing = _read_optional_bool(request.parameters.get("skip_missing"), default=False)
    has_default_value = "default_value" in request.parameters
    default_value = build_value_payload(request.parameters.get("default_value"))["value"] if has_default_value else None

    mapped_items: list[object] = []
    for item_index, item_value in enumerate(items_value):
        if path is None:
            mapped_items.append(item_value)
            continue
        exists, mapped_value = try_extract_value_by_path(root=item_value, path=path)
        if exists:
            mapped_items.append(mapped_value)
            continue
        if has_default_value:
            mapped_items.append(default_value)
            continue
        if skip_missing:
            continue
        raise InvalidRequestError(
            "list-map 节点无法从列表项提取指定 path",
            details={"node_id": request.node_id, "item_index": item_index, "path": path},
        )

    return {"value": build_value_payload(mapped_items)}


def _read_optional_map_path(raw_value: object) -> str | None:
    """读取 list-map 的可选映射路径。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("list-map 节点的 path 必须是非空字符串")
    return raw_value.strip()


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    raise InvalidRequestError("skip_missing 必须是布尔值")


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-map",
        display_name="Map List",
        category="logic.collection",
        description="按 path 逐项把列表映射为新的值列表，支持默认值和缺失项跳过。",
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
                "skip_missing": {"type": "boolean"},
                "default_value": {},
            },
        },
        capability_tags=("logic.collection", "list.map"),
    ),
    handler=_list_map_handler,
)