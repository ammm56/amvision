"""文件文本读取节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_reading import (
    DEFAULT_FILE_READ_MAX_BYTES,
    read_file_bytes,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按显式 charset 有界读取 file-ref 文本。"""

    payload, content = read_file_bytes(request)
    charset = request.parameters.get("charset", "utf-8")
    if not isinstance(charset, str) or not charset.strip():
        raise InvalidRequestError("File Read Text 的 charset 不能为空")
    try:
        text = content.decode(charset.strip())
    except (LookupError, UnicodeDecodeError) as exc:
        raise InvalidRequestError(
            "File Read Text 无法按指定 charset 解码文件",
            details={"charset": charset.strip(), "file_name": payload["file_name"]},
        ) from exc
    return {
        "text": {
            "text": text,
            "media_type": str(payload["media_type"]),
            "charset": charset.strip().lower(),
        }
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.file-read-text",
        display_name="File Read Text",
        category="core.io.file",
        description="按显式 charset 和字节上限读取 file-ref.v1 文本。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="file", display_name="File", payload_type_id="file-ref.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="text", display_name="Text", payload_type_id="text.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "charset": {"type": "string", "minLength": 1, "default": "utf-8"},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "default": DEFAULT_FILE_READ_MAX_BYTES,
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("file.read", "text"),
    ),
    handler=_handler,
)
