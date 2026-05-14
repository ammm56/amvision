"""列表装配逻辑节点。"""

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


def _list_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按参数项与输入项顺序组装列表值。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：组装后的列表 value payload。
    """

    items: list[object] = []
    parameter_items = _read_list_create_parameter_items(request.parameters.get("items"))
    items.extend(parameter_items)

    input_payloads = request.input_values.get("items")
    if input_payloads is not None and not isinstance(input_payloads, tuple):
        raise InvalidRequestError(
            "list-create 节点要求 items 输入必须是多值端口集合",
            details={"node_id": request.node_id},
        )
    for item_index, item_payload in enumerate(input_payloads or (), start=1):
        items.append(require_value_payload(item_payload, field_name=f"items[{item_index}]")["value"])

    return {"value": build_value_payload(items)}


def _read_list_create_parameter_items(raw_value: object) -> list[object]:
    """读取 list-create 的静态参数项。"""

    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise InvalidRequestError("list-create 节点的 items 参数必须是数组")
    return list(build_value_payload(raw_value)["value"])


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.list-create",
        display_name="Create List",
        category="logic.structure",
        description="按静态参数项与多路输入项的顺序组装一个列表 value payload。",
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
        },
        capability_tags=("logic.structure", "value.list.create"),
    ),
    handler=_list_create_handler,
)