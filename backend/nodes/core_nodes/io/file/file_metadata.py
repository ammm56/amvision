"""文件引用元数据读取节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_file_ref_payload
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """返回 file-ref 中公开且不可变的元数据。"""

    payload = require_file_ref_payload(request.input_values.get("file"))
    return {"metadata": build_value_payload(payload)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.file-metadata",
        display_name="File Metadata",
        category="core.io.file",
        description="读取 file-ref.v1 元数据，不读取文件内容。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="file", display_name="File", payload_type_id="file-ref.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="metadata", display_name="Metadata", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        capability_tags=("file.metadata",),
    ),
    handler=_handler,
)
