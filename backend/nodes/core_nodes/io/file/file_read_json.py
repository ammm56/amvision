"""文件 JSON 读取节点。"""

from __future__ import annotations

import json

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
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """有界读取并解析 UTF-8 JSON 文件。"""

    payload, content = read_file_bytes(request)
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidRequestError(
            "File Read JSON 收到的文件不是有效 UTF-8 JSON",
            details={"file_name": payload["file_name"]},
        ) from exc
    return {"value": build_value_payload(value)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.file-read-json",
        display_name="File Read JSON",
        category="core.io.file",
        description="按字节上限读取 file-ref.v1，并显式解析 UTF-8 JSON。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="file", display_name="File", payload_type_id="file-ref.v1"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value", display_name="Value", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "default": DEFAULT_FILE_READ_MAX_BYTES,
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("file.read", "logic.json"),
    ),
    handler=_handler,
)
