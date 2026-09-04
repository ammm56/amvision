"""本地文本读取节点，与 ObjectStore File Read Text 保持独立输入边界。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import build_local_file_summary
from backend.nodes.core_nodes.support.local_io.reading import (
    DEFAULT_TEXT_MAX_BYTES,
    read_local_bytes,
    read_positive_limit,
    resolve_file_source,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _text_load_local_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """按显式编码和大小上限读取文本，失败时不替换字符或重试。"""
    path, expected = resolve_file_source(request)
    charset = request.parameters.get("charset", "utf-8")
    if not isinstance(charset, str) or not charset.strip():
        raise InvalidRequestError("charset 必须是非空字符串")
    content, record = read_local_bytes(
        path,
        expected_record=expected,
        max_bytes=read_positive_limit(
            request.parameters, "max_bytes", DEFAULT_TEXT_MAX_BYTES
        ),
    )
    try:
        text = content.decode(charset.strip())
    except (LookupError, UnicodeDecodeError) as exc:
        raise InvalidRequestError(
            "本地文本无法按指定 charset 解码", details={"charset": charset}
        ) from exc
    return {
        "text": {
            "text": text,
            "media_type": "text/plain",
            "charset": charset.strip().lower(),
        },
        "summary": build_local_file_summary(local_path=path, file_record=record),
    }


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.text-load-local",
        display_name="Load Local Text",
        category="core.io.file",
        description="按路径或目录文件记录，有界读取本地文本并输出 text.v1。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="file",
                display_name="File",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="local_path", input_port_name="path"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="text", display_name="Text", payload_type_id="text.v1"
            ),
            NodePortDefinition(
                name="summary", display_name="Summary", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "title": "本地文本路径"},
                "charset": {
                    "type": "string",
                    "title": "字符编码",
                    "minLength": 1,
                    "default": "utf-8",
                },
                "max_bytes": {
                    "type": "integer",
                    "title": "最大字节数",
                    "minimum": 1,
                    "default": DEFAULT_TEXT_MAX_BYTES,
                },
            },
            "additionalProperties": False,
        },
        capability_tags=("io.input", "file.read", "text"),
    ),
    handler=_text_load_local_handler,
)
