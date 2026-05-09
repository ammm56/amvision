"""对象装配逻辑节点。"""

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


def _object_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按静态字段和多路值输入组装对象。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：组装后的对象 value payload。
    """

    result_object = _read_static_fields(request.parameters.get("fields"))
    value_payloads = request.input_values.get("values")
    if value_payloads is not None and not isinstance(value_payloads, tuple):
        raise InvalidRequestError(
            "object-create 节点要求 values 输入必须是多值端口集合",
            details={"node_id": request.node_id},
        )
    normalized_payloads = tuple(value_payloads or ())
    object_keys = _read_object_keys(request.parameters.get("keys"), expected_size=len(normalized_payloads))
    for value_index, (field_name, value_payload) in enumerate(zip(object_keys, normalized_payloads, strict=False), start=1):
        result_object[field_name] = require_value_payload(value_payload, field_name=f"values[{value_index}]")["value"]
    return {"value": build_value_payload(result_object)}


def _read_static_fields(raw_value: object) -> dict[str, object]:
    """读取 object-create 的静态字段参数。"""

    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise InvalidRequestError("object-create 节点的 fields 参数必须是对象")
    normalized_fields = build_value_payload(raw_value)["value"]
    if not isinstance(normalized_fields, dict):
        raise InvalidRequestError("object-create 节点的 fields 参数必须是对象")
    return dict(normalized_fields)


def _read_object_keys(raw_value: object, *, expected_size: int) -> tuple[str, ...]:
    """读取并校验 object-create 的动态字段名列表。"""

    if expected_size == 0:
        if raw_value is None:
            return ()
        if isinstance(raw_value, list) and not raw_value:
            return ()
        raise InvalidRequestError("object-create 节点在未提供 values 输入时不应声明 keys")

    if not isinstance(raw_value, list):
        raise InvalidRequestError("object-create 节点要求 keys 参数必须是字符串数组")
    if len(raw_value) != expected_size:
        raise InvalidRequestError(
            "object-create 节点的 keys 数量必须与 values 输入数量一致",
            details={"expected_size": expected_size, "actual_size": len(raw_value)},
        )
    normalized_keys: list[str] = []
    for key_index, raw_key in enumerate(raw_value, start=1):
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise InvalidRequestError(
                "object-create 节点的 keys 每一项都必须是非空字符串",
                details={"key_index": key_index},
            )
        normalized_key = raw_key.strip()
        if normalized_key in normalized_keys:
            raise InvalidRequestError(
                "object-create 节点的 keys 不能包含重复字段名",
                details={"field_name": normalized_key},
            )
        normalized_keys.append(normalized_key)
    return tuple(normalized_keys)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-create",
        display_name="Create Object",
        category="logic.structure",
        description="按静态 fields 参数和多路 values 输入组装一个对象 value payload。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
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
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "fields": {
                    "type": "object",
                },
            },
        },
        capability_tags=("logic.structure", "value.object.create"),
    ),
    handler=_object_create_handler,
)