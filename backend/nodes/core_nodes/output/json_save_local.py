"""本地 JSON 结果保存节点。"""

from __future__ import annotations

import json

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import (
    build_local_file_summary,
    resolve_local_output_file_path,
    resolve_value_or_result_input,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _json_save_local_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把结果对象或 value 内容保存为本地 JSON 文件。"""

    overwrite = _read_overwrite(request.parameters.get("overwrite"))
    output_path = resolve_local_output_file_path(
        request,
        parameter_name="local_path",
        overwrite=overwrite,
        description="本地 JSON 输出文件",
    )
    payload_value, source_kind = resolve_value_or_result_input(request)
    indent = _read_indent(request.parameters.get("indent"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = json.dumps(payload_value, ensure_ascii=False, indent=indent)
    output_path.write_text(output_text, encoding="utf-8")
    return {
        "summary": build_local_file_summary(
            local_path=output_path,
            extra_fields={
                "record_kind": source_kind,
                "indent": indent,
            },
        )
    }


def _read_overwrite(raw_value: object) -> bool:
    """读取覆盖参数。"""

    if raw_value is None:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("json-save-local 的 overwrite 必须是布尔值")
    return raw_value


def _read_indent(raw_value: object) -> int:
    """读取 JSON 缩进参数。"""

    if raw_value is None:
        return 2
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError("json-save-local 的 indent 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError("json-save-local 的 indent 不能小于 0")
    return raw_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.output.json-save-local",
        display_name="Save Local JSON",
        category="io.output",
        description="把 result-record 或 value 内容保存为本地 JSON 文件，适合工业现场结果归档。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="result-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="alarm",
                display_name="Alarm",
                payload_type_id="alarm-record.v1",
                required=False,
            ),
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(
                name="path",
                display_name="Path",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="summary",
                display_name="Summary",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "title": "本地 JSON 路径"},
                "overwrite": {"type": "boolean", "title": "允许覆盖", "default": True},
                "indent": {"type": "integer", "title": "JSON 缩进", "default": 2, "minimum": 0},
            },
        },
        capability_tags=("io.output", "inspection.result.persist", "json.save"),
    ),
    handler=_json_save_local_handler,
)
