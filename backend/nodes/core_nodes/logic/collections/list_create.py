"""列表装配逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.structure_items import require_list_item_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _list_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按静态列表或显式 index 的列表项组装列表值。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：组装后的列表 value payload。
    """

    parameter_items = _read_list_create_parameter_items(request.parameters.get("items"))
    entry_payloads = request.input_values.get("entries")
    if entry_payloads is not None and not isinstance(entry_payloads, tuple):
        raise InvalidRequestError(
            "list-build 节点要求 entries 输入必须是多值端口集合",
            details={"node_id": request.node_id},
        )
    normalized_entries = tuple(entry_payloads or ())
    if parameter_items and normalized_entries:
        raise InvalidRequestError(
            "list-build 节点不能同时使用静态 items 和动态 entries",
            details={"node_id": request.node_id},
        )
    if not normalized_entries:
        return {"value": build_value_payload(parameter_items)}

    indexed_values: dict[int, object] = {}
    for entry_position, entry_payload in enumerate(normalized_entries, start=1):
        item_index, item_value = require_list_item_payload(
            entry_payload,
            field_name=f"entries[{entry_position}]",
        )
        if item_index in indexed_values:
            raise InvalidRequestError(
                "list-build 节点的 entries 不能包含重复 index",
                details={"node_id": request.node_id, "index": item_index},
            )
        indexed_values[item_index] = item_value
    actual_indices = sorted(indexed_values)
    expected_indices = list(range(len(indexed_values)))
    if actual_indices != expected_indices:
        raise InvalidRequestError(
            "list-build 节点的 entries index 必须从 0 开始且连续",
            details={
                "node_id": request.node_id,
                "expected_indices": expected_indices,
                "actual_indices": actual_indices,
            },
        )
    return {
        "value": build_value_payload(
            [indexed_values[item_index] for item_index in expected_indices]
        )
    }


def _read_list_create_parameter_items(raw_value: object) -> list[object]:
    """读取 list-build 的静态参数项。"""

    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise InvalidRequestError("list-build 节点的 items 参数必须是数组")
    return list(build_value_payload(raw_value)["value"])


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-build",
        display_name="Create List",
        category="core.logic.collection",
        description="使用静态 items，或按多个 list-item.v1 的显式 index 组装列表；不依赖连线顺序。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="entries",
                display_name="Items",
                payload_type_id="list-item.v1",
                required=False,
                multiple=True,
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
                "items": {
                    "type": "array",
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("logic.structure", "value.list.create"),
    ),
    handler=_list_create_handler,
)
