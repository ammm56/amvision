"""模板单文件输入节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_file_ref_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """只透传文件引用，不读取文件内容。"""

    return {
        "file": require_file_ref_payload(
            request.input_values.get("payload"), field_name="payload"
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.template-input.file",
        display_name="Template File Input",
        category="core.io.input",
        description="把流程应用绑定进来的单文件 ObjectStore 引用透传给后续节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="payload", display_name="Payload", payload_type_id="file-ref.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="file", display_name="File", payload_type_id="file-ref.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        capability_tags=("io.input", "file.reference", "execution.pure"),
    ),
    handler=_handler,
)
