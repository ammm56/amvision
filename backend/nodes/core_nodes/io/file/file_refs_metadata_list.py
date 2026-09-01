"""多文件引用元数据列表节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_file_refs_payload
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按上传顺序返回文件引用元数据列表，不读取任何文件内容。"""

    payload = require_file_refs_payload(request.input_values.get("files"))
    return {"metadata": build_value_payload(payload["items"])}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.file-refs-metadata-list",
        display_name="File Refs Metadata List",
        category="core.io.file",
        description="按上传顺序把 file-refs.v1 转为元数据 value 列表，不读取文件字节或改变文件引用。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
        input_ports=(
            NodePortDefinition(
                name="files",
                display_name="Files",
                payload_type_id="file-refs.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="metadata",
                display_name="Metadata",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        capability_tags=(
            "file.metadata",
            "logic.list",
            "execution.pure",
        ),
    ),
    handler=_handler,
)
