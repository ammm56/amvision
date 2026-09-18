"""有界读取本地 JSONL 记录。"""

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.jsonl_nodes import (
    READ_BINDINGS,
    READ_PORTS,
    READ_PROPERTIES,
    input_value,
    read_options,
    source_path,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.runtime.io.jsonl import read_records
from backend.service.application.runtime.io.file_errors import file_io_errors
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """读取单批记录并输出可继续使用的游标和固定边界。"""
    path = source_path(request)
    with file_io_errors(path, operation="read_jsonl"):
        result = read_records(
            path,
            cursor=input_value(request, "cursor"),
            snapshot_end=input_value(request, "snapshot_end"),
            **read_options(request),
        )
    return {key: build_value_payload(value) for key, value in result.items()}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.jsonl-load-local",
        display_name="Read JSONL",
        category="core.io.file",
        description="按完整记录和固定提交边界读取 JSONL；不计算业务指标。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=READ_PORTS
        + tuple(
            NodePortDefinition(
                name=key, display_name=key, payload_type_id="value.v1", required=False
            )
            for key in ("cursor", "snapshot_end")
        ),
        parameter_input_bindings=READ_BINDINGS,
        output_ports=tuple(
            NodePortDefinition(name=key, display_name=key, payload_type_id="value.v1")
            for key in ("records", "next_cursor", "snapshot_end", "has_more", "status")
        ),
        parameter_schema={"type": "object", "properties": READ_PROPERTIES},
        capability_tags=("io.input", "jsonl.read"),
    ),
    handler=_handler,
)
