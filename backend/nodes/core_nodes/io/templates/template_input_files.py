"""模板多文件输入节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_file_refs_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按请求顺序透传文件引用数组，不读取文件内容。"""

    return {
        "files": require_file_refs_payload(
            request.input_values.get("payload"), field_name="payload"
        )
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.template-input.files",
        display_name="Template Files Input",
        category="core.io.input",
        description="把流程应用绑定进来的有序多文件 ObjectStore 引用透传给后续节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="payload", display_name="Payload", payload_type_id="file-refs.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="files", display_name="Files", payload_type_id="file-refs.v1"
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
