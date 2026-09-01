"""对象字段更新逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.object import copy_object_value, require_object_value, set_object_path
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _object_update_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按单个明确路径更新对象字段。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：更新后的对象 value payload。
    """

    object_value = require_object_value(
        request.input_values.get("object"),
        field_name="object",
        node_id=request.node_id,
    )
    value_payload = require_value_payload(
        request.input_values.get("value"),
        field_name="value",
    )
    raw_path = request.parameters.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise InvalidRequestError(
            "object-set-path 节点的 path 必须是非空字符串",
            details={"node_id": request.node_id},
        )
    if raw_path != raw_path.strip():
        raise InvalidRequestError(
            "object-set-path 节点的 path 不能包含首尾空白字符",
            details={"node_id": request.node_id},
        )
    updated_object = copy_object_value(object_value)
    set_object_path(
        updated_object,
        path=raw_path,
        value=value_payload["value"],
    )
    return {"value": build_value_payload(updated_object)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-set-path",
        display_name="Set Object Path",
        category="core.logic.object",
        description="按一个明确 path 更新一个值；多个字段通过节点串联，避免 paths 与 values 的位置配对。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="object",
                display_name="Object",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
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
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Path",
                    "description": "明确字段路径，例如 status 或 meta.reviewer。",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="path",
                input_port_name="path",
            ),
        ),
        capability_tags=("logic.structure", "value.object.update"),
        metadata={"title_parameter": "path"},
    ),
    handler=_object_update_handler,
)
