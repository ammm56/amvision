"""对象字段更新逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._object_node_support import copy_object_value, read_object_paths, require_object_value, set_object_path
from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _object_update_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按静态字段路径更新对象字段。

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
    updated_object = copy_object_value(object_value)
    _apply_static_updates(updated_object, raw_updates=request.parameters.get("updates"))

    value_payloads = request.input_values.get("values")
    if value_payloads is not None and not isinstance(value_payloads, tuple):
        raise InvalidRequestError(
            "object-update 节点要求 values 输入必须是多值端口集合",
            details={"node_id": request.node_id},
        )
    normalized_payloads = tuple(value_payloads or ())
    if normalized_payloads:
        paths = read_object_paths(request.parameters.get("paths"), field_name="paths")
        if len(paths) != len(normalized_payloads):
            raise InvalidRequestError(
                "object-update 节点的 paths 数量必须与 values 输入数量一致",
                details={"node_id": request.node_id, "expected_size": len(paths), "actual_size": len(normalized_payloads)},
            )
        for value_index, (path, value_payload) in enumerate(zip(paths, normalized_payloads, strict=False), start=1):
            set_object_path(
                updated_object,
                path=path,
                value=require_value_payload(value_payload, field_name=f"values[{value_index}]")["value"],
            )
    return {"value": build_value_payload(updated_object)}


def _apply_static_updates(target: dict[str, object], *, raw_updates: object) -> None:
    """应用 object-update 的静态更新参数。"""

    if raw_updates is None:
        return
    if not isinstance(raw_updates, dict):
        raise InvalidRequestError("object-update 节点的 updates 参数必须是对象")
    for raw_path, raw_value in raw_updates.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise InvalidRequestError("object-update 节点的 updates 键必须是非空字段路径")
        set_object_path(target, path=raw_path.strip(), value=raw_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-update",
        display_name="Update Object Fields",
        category="logic.structure",
        description="按静态字段路径更新对象字段，支持固定 updates 与多路 values 输入。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="object",
                display_name="Object",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="values",
                display_name="Values",
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
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "updates": {
                    "type": "object",
                },
            },
        },
        capability_tags=("logic.structure", "value.object.update"),
    ),
    handler=_object_update_handler,
)