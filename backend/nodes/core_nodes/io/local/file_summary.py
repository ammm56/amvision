"""通用文件增量汇总节点。"""

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.file_summary import summarize
from backend.nodes.core_nodes.support.jsonl_nodes import (
    READ_BINDINGS,
    READ_PORTS,
    READ_PROPERTIES,
    read_options,
    source_path,
)
from backend.nodes.core_nodes.support.local_io.paths import (
    resolve_local_path_value_from_request,
)
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.runtime.io import try_acquire_path_write_locks
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """文件读取和计算不持生产写锁，检查点使用独立路径。"""
    path = source_path(request)
    state_path = resolve_local_path_value_from_request(
        request,
        parameter_name="state_path",
        input_name="state_path",
        description="汇总检查点",
    )
    options = read_options(request)
    options["allow_missing"] = request.parameters.get("allow_missing", True)
    result = summarize(
        path,
        state_path,
        reducers=request.parameters.get("reducers"),
        condition=request.parameters.get("condition"),
        lock=try_acquire_path_write_locks(request, (state_path,)),
        **options,
    )
    return {"snapshot": build_value_payload(result)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.file-summary",
        display_name="File Summary",
        category="core.io.file",
        description="按指定字段增量汇总单个 JSONL 文件；检查点可恢复，不内置业务字段。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=READ_PORTS
        + (
            NodePortDefinition(
                name="state_path",
                display_name="State Path",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        parameter_input_bindings=READ_BINDINGS
        + (
            NodeParameterInputBinding(
                parameter_name="state_path", input_port_name="state_path"
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="snapshot", display_name="Snapshot", payload_type_id="value.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "required": ["reducers"],
            "properties": {
                **READ_PROPERTIES,
                "allow_missing": {"type": "boolean", "default": True},
                "state_path": {"type": "string", "title": "State Path"},
                "condition": {"type": "object", "title": "Filter"},
                "reducers": {
                    "type": "array",
                    "title": "Reducers",
                    "x-ui-widget": "object-rows",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {
                        "type": "object",
                        "required": ["output_key", "operation"],
                        "properties": {
                            "output_key": {"type": "string", "minLength": 1},
                            "source_path": {"type": "string"},
                            "operation": {
                                "type": "string",
                                "enum": ["sum", "count", "min", "max", "last"],
                            },
                            "numeric_type": {
                                "type": "string",
                                "enum": ["integer", "number"],
                                "default": "integer",
                            },
                            "missing_policy": {
                                "type": "string",
                                "enum": ["error", "skip"],
                                "default": "error",
                            },
                        },
                    },
                },
            },
        },
        capability_tags=("io.input", "file.summary"),
    ),
    handler=_handler,
)
