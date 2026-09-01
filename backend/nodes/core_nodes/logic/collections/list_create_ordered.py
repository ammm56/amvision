"""旧版连线顺序列表创建节点，仅用于已发布 workflow 兼容执行。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _legacy_list_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按旧版静态项和多值输入顺序创建列表。"""

    raw_items = request.parameters.get("items")
    if raw_items is None:
        items: list[object] = []
    elif isinstance(raw_items, list):
        items = list(build_value_payload(raw_items)["value"])
    else:
        raise InvalidRequestError("旧版 list-create 的 items 参数必须是数组")
    input_payloads = request.input_values.get("items")
    if input_payloads is not None and not isinstance(input_payloads, tuple):
        raise InvalidRequestError("旧版 list-create 的 items 输入必须是多值端口集合")
    for item_index, item_payload in enumerate(input_payloads or (), start=1):
        items.append(
            require_value_payload(item_payload, field_name=f"items[{item_index}]")["value"]
        )
    return {"value": build_value_payload(items)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-create",
        display_name="Create List (Legacy Ordered)",
        category="core.logic.collection",
        description="仅兼容已发布 workflow；新流程必须使用 List Item + Create List。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="items",
                display_name="Items",
                payload_type_id="value.v1",
                required=False,
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
        ),
        parameter_schema={"type": "object", "properties": {"items": {"type": "array"}}},
        capability_tags=("logic.structure", "value.list.create", "compatibility.legacy"),
        metadata={
            "deprecated": True,
            "palette_hidden": True,
            "replacement_node_type_id": "core.logic.list-build",
            "legacy_behavior": "ordered-input-binding",
        },
    ),
    handler=_legacy_list_create_handler,
)
