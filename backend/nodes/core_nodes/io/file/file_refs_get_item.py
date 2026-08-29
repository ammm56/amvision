"""有序文件引用取项节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_payloads import require_file_refs_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按显式索引返回一个 file-ref，保持请求上传顺序。"""

    payload = require_file_refs_payload(request.input_values.get("files"))
    index = request.parameters.get("index", 0)
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise InvalidRequestError("File Refs Get Item 的 index 必须是非负整数")
    items = payload["items"]
    if index >= len(items):
        raise InvalidRequestError(
            "File Refs Get Item 的 index 超出范围",
            details={"index": index, "count": len(items)},
        )
    return {"file": items[index]}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.file-refs-get-item",
        display_name="File Refs Get Item",
        category="core.logic.value",
        description="按索引从 file-refs.v1 有序数组中取出一个 file-ref.v1。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="files", display_name="Files", payload_type_id="file-refs.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="file", display_name="File", payload_type_id="file-ref.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {"index": {"type": "integer", "minimum": 0, "default": 0}},
            "additionalProperties": False,
        },
        capability_tags=("logic.list", "file.reference"),
    ),
    handler=_handler,
)
