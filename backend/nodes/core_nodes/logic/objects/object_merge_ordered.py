"""旧版顺序覆盖对象合并节点，仅用于已发布 workflow 兼容执行。"""

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


def _legacy_object_merge_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按旧版多值输入顺序执行后者覆盖前者。"""

    raw_base = request.parameters.get("base")
    merged_object = {} if raw_base is None else build_value_payload(raw_base)["value"]
    if not isinstance(merged_object, dict):
        raise InvalidRequestError("旧版 object-merge 的 base 必须是对象")
    object_payloads = request.input_values.get("objects")
    if object_payloads is not None and not isinstance(object_payloads, tuple):
        raise InvalidRequestError("旧版 object-merge 的 objects 必须是多值端口集合")
    result = dict(merged_object)
    for object_index, object_payload in enumerate(object_payloads or (), start=1):
        object_value = require_value_payload(
            object_payload,
            field_name=f"objects[{object_index}]",
        )["value"]
        if not isinstance(object_value, dict):
            raise InvalidRequestError("旧版 object-merge 的每个输入都必须是对象")
        result.update(object_value)
    return {"value": build_value_payload(result)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-merge",
        display_name="Merge Objects (Legacy Ordered)",
        category="core.logic.object",
        description="仅兼容已发布 workflow；新流程必须使用明确 Base 与 Overlay 的 Merge Objects。",
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
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
        ),
        parameter_schema={"type": "object", "properties": {"base": {"type": "object"}}},
        capability_tags=("logic.structure", "value.object.merge", "compatibility.legacy"),
        metadata={
            "deprecated": True,
            "palette_hidden": True,
            "replacement_node_type_id": "core.logic.object-merge-pair",
            "legacy_behavior": "ordered-overwrite",
        },
    ),
    handler=_legacy_object_merge_handler,
)
