"""对象装配逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.structure_items import require_object_field_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _object_create_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按静态字段和显式对象字段项组装对象。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：组装后的对象 value payload。
    """

    if "keys" in request.parameters:
        raise InvalidRequestError(
            "object-build 不支持 keys 与 values 的位置配对，请使用 Object Field 节点",
            details={"node_id": request.node_id, "legacy_parameter": "keys"},
        )
    result_object = _read_static_fields(request.parameters.get("fields"))
    entry_payloads = request.input_values.get("entries")
    if entry_payloads is not None and not isinstance(entry_payloads, tuple):
        raise InvalidRequestError(
            "object-build 节点要求 entries 输入必须是多值端口集合",
            details={"node_id": request.node_id},
        )
    for entry_index, entry_payload in enumerate(entry_payloads or (), start=1):
        field_name, field_value = require_object_field_payload(
            entry_payload,
            field_name=f"entries[{entry_index}]",
        )
        if field_name in result_object:
            raise InvalidRequestError(
                "object-build 节点存在重复字段名",
                details={
                    "node_id": request.node_id,
                    "field_name": field_name,
                    "entry_index": entry_index,
                },
            )
        result_object[field_name] = field_value
    stable_result = {field_name: result_object[field_name] for field_name in sorted(result_object)}
    return {"value": build_value_payload(stable_result)}


def _read_static_fields(raw_value: object) -> dict[str, object]:
    """读取 object-build 的静态字段参数。"""

    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise InvalidRequestError("object-build 节点的 fields 参数必须是对象")
    normalized_fields = build_value_payload(raw_value)["value"]
    if not isinstance(normalized_fields, dict):
        raise InvalidRequestError("object-build 节点的 fields 参数必须是对象")
    return dict(normalized_fields)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-build",
        display_name="Create Object",
        category="core.logic.object",
        description="按静态 fields 参数和多个显式 object-field.v1 输入组装对象；字段语义不依赖连线顺序。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="entries",
                display_name="Fields",
                payload_type_id="object-field.v1",
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
                "fields": {
                    "type": "object",
                    "title": "Fields",
                    "description": "静态固定字段对象，会直接写入结果；例如 {\"source\": \"workflow-preview\", \"ok\": true}。",
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("logic.structure", "value.object.create"),
    ),
    handler=_object_create_handler,
)
