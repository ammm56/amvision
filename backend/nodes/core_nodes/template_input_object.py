"""模板输入对象节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _template_input_object_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把模板注入的对象 value payload 透传为节点输出。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：透传后的对象 value payload 输出。
    """

    payload = require_value_payload(request.input_values.get("payload"), field_name="payload")
    object_value = payload["value"]
    if not isinstance(object_value, dict):
        raise InvalidRequestError(
            "Template Object Input 节点要求 payload.value 必须是对象",
            details={"node_id": request.node_id},
        )
    return {"value": {"value": dict(object_value)}}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.template-input.object",
        display_name="Template Object Input",
        category="io.input",
        description="把流程应用绑定进来的对象 value payload 透传给后续节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="payload",
                display_name="Payload",
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
        parameter_schema={"type": "object", "properties": {}},
        capability_tags=("io.input",),
    ),
    handler=_template_input_object_handler,
)