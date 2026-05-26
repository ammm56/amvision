"""模板输入 value 节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import require_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _template_input_value_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把模板注入的 value payload 直接透传为节点输出。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：透传后的 value payload 输出。
    """

    return {"value": require_value_payload(request.input_values.get("payload"), field_name="payload")}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.template-input.value",
        display_name="Template Value Input",
        category="io.input",
        description="把流程应用绑定进来的 value payload 透传给后续节点。",
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
    handler=_template_input_value_handler,
)