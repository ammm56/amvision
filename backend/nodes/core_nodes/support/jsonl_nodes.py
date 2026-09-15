"""JSONL 节点共用参数、来源和读取预算。"""

from backend.contracts.workflows.workflow_graph import (
    NodePortDefinition,
    NodeParameterInputBinding,
)
from backend.nodes.core_nodes.support.local_io.reading import resolve_file_source
from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.runtime.io.jsonl import (
    DEFAULT_READ_BYTES,
    DEFAULT_READ_MS,
    DEFAULT_READ_RECORDS,
)

READ_PORTS = tuple(
    NodePortDefinition(
        name=name, display_name=name.title(), payload_type_id="value.v1", required=False
    )
    for name in ("file", "path")
)
READ_BINDINGS = (
    NodeParameterInputBinding(parameter_name="local_path", input_port_name="path"),
)
READ_PROPERTIES = {
    "local_path": {"type": "string", "title": "Local Path"},
    "source_mode": {
        "type": "string",
        "enum": ["managed", "snapshot"],
        "default": "managed",
        "title": "Source Mode",
    },
    "allow_missing": {"type": "boolean", "default": False, "title": "Allow Missing"},
    "max_records": {
        "type": "integer",
        "minimum": 1,
        "maximum": 100000,
        "default": DEFAULT_READ_RECORDS,
        "title": "Max Records",
    },
    "max_bytes": {
        "type": "integer",
        "minimum": 1,
        "maximum": 67108864,
        "default": DEFAULT_READ_BYTES,
        "title": "Max Bytes",
    },
    "max_ms": {
        "type": "integer",
        "minimum": 1,
        "maximum": 5000,
        "default": DEFAULT_READ_MS,
        "title": "Max Time",
    },
}


def input_value(request, name, default=None):
    """读取通用 value.v1 可选输入。"""
    payload = request.input_values.get(name)
    return (
        require_value_payload(payload, field_name=name)["value"]
        if payload is not None
        else default
    )


def read_options(request):
    """集中预算默认值，避免 reader 与节点各自决定。"""
    from backend.service.application.workflows.execution.execution_control import (
        build_node_execution_control,
    )

    return {
        "check_control": build_node_execution_control(
            request
        ).raise_if_cancelled_or_expired,
        **{
            key: request.parameters.get(key, value["default"])
            for key, value in READ_PROPERTIES.items()
            if "default" in value
        },
    }


def source_path(request):
    """沿用本地文件来源；已观察的静态记录由 snapshot 模式读取。"""
    path, expected = resolve_file_source(request)
    if expected is not None:
        from backend.nodes.core_nodes.support.local_io.files import (
            build_directory_file_record,
        )
        from backend.service.application.runtime.io.jsonl import fail

        if (
            build_directory_file_record(path)["observed_version"]
            != expected["observed_version"]
        ):
            raise fail("选择的 JSONL 文件已变化")
    return path
