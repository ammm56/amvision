"""对象字段移除逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._object_node_support import copy_object_value, read_object_paths, remove_object_path, require_object_value
from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _object_remove_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按静态字段路径从对象中移除子字段。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：移除字段后的对象 value payload。
    """

    object_value = require_object_value(
        request.input_values.get("object"),
        field_name="object",
        node_id=request.node_id,
    )
    paths = read_object_paths(request.parameters.get("paths"), field_name="paths")
    updated_object = copy_object_value(object_value)
    for path in paths:
        remove_object_path(updated_object, path=path)
    return {"value": build_value_payload(updated_object)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-remove",
        display_name="Remove Object Fields",
        category="logic.structure",
        description="按静态字段路径从对象中移除子字段，适合 workflow app 的结果清洗。",
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
        capability_tags=("logic.structure", "value.object.remove"),
    ),
    handler=_object_remove_handler,
)