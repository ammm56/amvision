"""对象合并逻辑节点。"""

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


def _object_merge_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按输入顺序合并多个对象，后者覆盖前者同名字段。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：合并后的对象 value payload。
    """

    merged_object = _read_base_object(request.parameters.get("base"))
    object_payloads = request.input_values.get("objects")
    if object_payloads is not None and not isinstance(object_payloads, tuple):
        raise InvalidRequestError(
            "object-merge 节点要求 objects 输入必须是多值端口集合",
            details={"node_id": request.node_id},
        )
    for object_index, object_payload in enumerate(object_payloads or (), start=1):
        object_value = require_value_payload(object_payload, field_name=f"objects[{object_index}]")["value"]
        if not isinstance(object_value, dict):
            raise InvalidRequestError(
                "object-merge 节点要求每个 objects 输入都必须是对象值",
                details={"node_id": request.node_id, "object_index": object_index},
            )
        merged_object.update(object_value)
    return {"value": build_value_payload(merged_object)}


def _read_base_object(raw_value: object) -> dict[str, object]:
    """读取 object-merge 的静态基础对象。"""

    if raw_value is None:
        return {}
    normalized_value = build_value_payload(raw_value)["value"]
    if not isinstance(normalized_value, dict):
        raise InvalidRequestError("object-merge 节点的 base 参数必须是对象")
    return dict(normalized_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-merge",
        display_name="Merge Objects",
        category="logic.structure",
        description="按输入顺序合并多个对象，后者覆盖前者同名字段。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="objects",
                display_name="Objects",
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
                "base": {
                    "type": "object",
                },
            },
        },
        capability_tags=("logic.structure", "value.object.merge"),
    ),
    handler=_object_merge_handler,
)