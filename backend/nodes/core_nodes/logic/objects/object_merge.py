"""对象合并逻辑节点。"""

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


def _object_merge_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按明确 Base 与 Overlay 方向合并两个对象。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：合并后的对象 value payload。
    """

    base_object = _read_object_input(request.input_values.get("base"), field_name="base")
    overlay_object = _read_object_input(request.input_values.get("overlay"), field_name="overlay")
    duplicate_keys = sorted(set(base_object) & set(overlay_object))
    conflict_policy = request.parameters.get("conflict_policy", "error")
    if duplicate_keys and conflict_policy == "error":
        raise InvalidRequestError(
            "object-merge-pair 节点发现同名字段，当前 conflict_policy 禁止覆盖",
            details={"node_id": request.node_id, "duplicate_keys": duplicate_keys},
        )
    if conflict_policy not in {"error", "overwrite"}:
        raise InvalidRequestError(
            "object-merge-pair 节点的 conflict_policy 无效",
            details={"node_id": request.node_id, "conflict_policy": conflict_policy},
        )
    merged_object = {**base_object, **overlay_object}
    stable_result = {field_name: merged_object[field_name] for field_name in sorted(merged_object)}
    return {"value": build_value_payload(stable_result)}


def _read_object_input(raw_value: object, *, field_name: str) -> dict[str, object]:
    """读取一个必需的对象 value.v1 输入。"""

    normalized_value = require_value_payload(raw_value, field_name=field_name)["value"]
    if not isinstance(normalized_value, dict):
        raise InvalidRequestError(
            f"object-merge-pair 节点的 {field_name} 输入必须是对象值",
            details={"field_name": field_name},
        )
    return dict(normalized_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-merge-pair",
        display_name="Merge Objects",
        category="core.logic.object",
        description="按明确的 Base 与 Overlay 方向合并两个对象；字段冲突默认报错，可显式允许 Overlay 覆盖。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="base",
                display_name="Base",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="overlay",
                display_name="Overlay",
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
                "conflict_policy": {
                    "type": "string",
                    "enum": ["error", "overwrite"],
                    "default": "error",
                    "title": "Conflict Policy",
                    "description": "error 在同名字段时失败；overwrite 明确使用 Overlay 覆盖 Base。",
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("logic.structure", "value.object.merge"),
    ),
    handler=_object_merge_handler,
)
