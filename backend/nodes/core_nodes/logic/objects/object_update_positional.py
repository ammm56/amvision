"""旧版多路径对象更新节点，仅用于已发布 workflow 兼容执行。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.object import copy_object_value, read_object_paths, require_object_value, set_object_path
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _legacy_object_update_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行旧版 paths 与 values 位置配对更新。"""

    object_value = require_object_value(
        request.input_values.get("object"),
        field_name="object",
        node_id=request.node_id,
    )
    updated_object = copy_object_value(object_value)
    raw_updates = request.parameters.get("updates")
    if raw_updates is not None:
        if not isinstance(raw_updates, dict):
            raise InvalidRequestError("旧版 object-update 的 updates 必须是对象")
        for raw_path, raw_value in raw_updates.items():
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise InvalidRequestError("旧版 object-update 的 updates 键必须是非空路径")
            set_object_path(updated_object, path=raw_path.strip(), value=raw_value)

    value_payloads = request.input_values.get("values")
    if value_payloads is not None and not isinstance(value_payloads, tuple):
        raise InvalidRequestError("旧版 object-update 的 values 必须是多值端口集合")
    normalized_payloads = tuple(value_payloads or ())
    if normalized_payloads:
        paths = read_object_paths(request.parameters.get("paths"), field_name="paths")
        if len(paths) != len(normalized_payloads):
            raise InvalidRequestError("旧版 object-update 的 paths 与 values 数量必须一致")
        for value_index, (path, value_payload) in enumerate(
            zip(paths, normalized_payloads, strict=False),
            start=1,
        ):
            set_object_path(
                updated_object,
                path=path,
                value=require_value_payload(
                    value_payload,
                    field_name=f"values[{value_index}]",
                )["value"],
            )
    return {"value": build_value_payload(updated_object)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-update",
        display_name="Update Object Fields (Legacy Positional)",
        category="core.logic.object",
        description="仅兼容已发布 workflow；新流程必须串联 Set Object Path。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(name="object", display_name="Object", payload_type_id="value.v1"),
            NodePortDefinition(
                name="values",
                display_name="Values",
                payload_type_id="value.v1",
                required=False,
                multiple=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "updates": {"type": "object"},
            },
        },
        capability_tags=("logic.structure", "value.object.update", "compatibility.legacy"),
        metadata={
            "deprecated": True,
            "palette_hidden": True,
            "replacement_node_type_id": "core.logic.object-set-path",
            "legacy_behavior": "positional-input-binding",
        },
    ),
    handler=_legacy_object_update_handler,
)
