"""对象字段挑选逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._object_node_support import read_object_paths, require_object_value, set_object_path, try_read_object_path
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _object_pick_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按静态字段路径从对象中挑选子字段。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：挑选后的对象 value payload。
    """

    object_value = require_object_value(
        request.input_values.get("object"),
        field_name="object",
        node_id=request.node_id,
    )
    paths = read_object_paths(request.parameters.get("paths"), field_name="paths")
    picked_object: dict[str, object] = {}
    for path in paths:
        exists, picked_value = try_read_object_path(object_value, path=path)
        if not exists:
            raise InvalidRequestError(
                "object-pick 节点要求指定字段路径必须存在",
                details={"node_id": request.node_id, "path": path},
            )
        set_object_path(picked_object, path=path, value=picked_value)
    return {"value": build_value_payload(picked_object)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-pick",
        display_name="Pick Object Fields",
        category="logic.structure",
        description="按静态字段路径从对象中挑选子字段，适合 workflow app 的输出裁剪。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="object",
                display_name="Object",
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
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["paths"],
        },
        capability_tags=("logic.structure", "value.object.pick"),
    ),
    handler=_object_pick_handler,
)