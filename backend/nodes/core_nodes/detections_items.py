"""detections 列表提取节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _detections_items_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 detections payload 提取为可直接进入响应对象的列表。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包装后的 value payload，内部值为 detection item 列表。
    """

    detections_payload = request.input_values.get("detections")
    if not isinstance(detections_payload, dict):
        raise InvalidRequestError("detections-items 节点要求 detections payload 必须是对象")
    raw_items = detections_payload.get("items")
    if not isinstance(raw_items, list):
        raise InvalidRequestError("detections-items 节点要求 detections.items 必须是数组")

    normalized_items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InvalidRequestError("detections-items 节点要求每个 detection item 必须是对象")
        normalized_items.append(dict(item))
    return {"value": build_value_payload(normalized_items)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.detections-items",
        display_name="Detections Items",
        category="logic.transform",
        description="把 detections.v1 payload 提取成可直接装配到响应对象里的 detection item 列表。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
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
            "properties": {},
        },
        capability_tags=("logic.transform", "detections.items"),
    ),
    handler=_detections_items_handler,
)