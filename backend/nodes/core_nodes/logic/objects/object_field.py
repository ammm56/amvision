"""显式对象字段节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.nodes.core_nodes.support.structure_items import build_object_field_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _object_field_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把明确字段名和值组合成不可拆分的 object-field.v1。"""

    value_payload = require_value_payload(
        request.input_values.get("value"),
        field_name="value",
    )
    raw_key = request.parameters.get("key")
    if not isinstance(raw_key, str):
        raise InvalidRequestError(
            "object-field 节点的 key 必须是字符串",
            details={"node_id": request.node_id},
        )
    return {
        "field": build_object_field_payload(
            key=raw_key,
            value=value_payload["value"],
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.object-field",
        display_name="Object Field",
        category="core.logic.object",
        description="把字段名和值显式绑定成 object-field.v1；移动节点或改变连线存储顺序不会拆散两者。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="key",
                display_name="Key",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="field",
                display_name="Field",
                payload_type_id="object-field.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "title": "Key",
                    "description": "结果对象中的明确顶层字段名，不解析点分路径。可使用固定文本，也可以连接 value.v1 动态提供。",
                },
            },
            "required": ["key"],
            "additionalProperties": False,
        },
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="key",
                input_port_name="key",
            ),
        ),
        capability_tags=("logic.structure", "value.object.field"),
        metadata={"title_parameter": "key"},
    ),
    handler=_object_field_handler,
)
