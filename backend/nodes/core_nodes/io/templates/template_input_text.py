"""模板文本输入节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_text_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """透传经过闭合校验的 text.v1 payload。"""

    return {
        "text": require_text_payload(
            request.input_values.get("payload"), field_name="payload"
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.template-input.text",
        display_name="Template Text Input",
        category="core.io.input",
        description="把流程应用绑定进来的文本 payload 透传给后续节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="payload", display_name="Payload", payload_type_id="text.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="text", display_name="Text", payload_type_id="text.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        capability_tags=("io.input", "execution.pure"),
    ),
    handler=_handler,
)
