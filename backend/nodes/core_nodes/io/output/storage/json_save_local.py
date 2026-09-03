"""本地 JSON 结果保存节点。"""

from __future__ import annotations

from datetime import datetime
import json

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.local_io import resolve_value_or_result_input
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.file_name_template import (
    render_file_name_template,
    require_file_name_suffix,
)
from backend.nodes.save_node_contracts import (
    build_save_target_input_ports,
    build_save_target_parameter_input_bindings,
    build_save_target_parameter_properties,
    build_save_target_required_parameters,
    read_save_overwrite,
)
from backend.nodes.save_locations import (
    build_save_template_context,
    resolve_required_save_directory,
    save_bytes,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def _json_save_local_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """把结果对象或 value 内容保存到 ObjectStore 或系统文件。"""

    overwrite = read_save_overwrite(
        request.parameters.get("overwrite"),
        node_label="Save JSON",
    )
    current_time = datetime.now().astimezone()
    format_context = build_save_template_context(
        request,
        current_time=current_time,
    )
    rendered_directory, save_location = resolve_required_save_directory(
        request,
        request.parameters.get("save_directory"),
        node_label="Save JSON",
        current_time=current_time,
        context=format_context,
    )
    file_name = render_file_name_template(
        request.parameters.get("file_name"),
        node_label="Save JSON",
        current_time=current_time,
        context=format_context,
    )
    require_file_name_suffix(
        file_name,
        node_label="Save JSON",
        supported_suffixes={".json"},
    )
    payload_value, source_kind = resolve_value_or_result_input(request)
    indent = _read_indent(request.parameters.get("indent"))
    output_bytes = json.dumps(payload_value, ensure_ascii=False, indent=indent).encode(
        "utf-8"
    )
    saved_file = save_bytes(
        request,
        save_location=save_location,
        content=output_bytes,
        file_name=file_name,
        overwrite=overwrite,
        increment_on_conflict=not overwrite,
    )
    return {
        "summary": build_value_payload(
            {
                "saved_output": saved_file.to_payload(),
                "save_directory": rendered_directory,
                "file_name": file_name,
                "size_bytes": len(output_bytes),
                "record_kind": source_kind,
                "indent": indent,
            }
        )
    }


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
        display_name="Save JSON",
        category="core.io.file",
        description="把 result-record 或 value 内容保存到 ObjectStore 或 runtime 主机文件。",
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
            *build_save_target_input_ports(include_overwrite=True),
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
                **build_save_target_parameter_properties(
                    overwrite_default=False,
                    file_name_example=(
                        "result-{YYYY}-{MM}-{DD}-{hh}-{mm}-{ss}-{SSS}.json"
                    ),
                ),
                "indent": {
                    "type": "integer",
                    "title": "JSON 缩进",
                    "default": 2,
                    "minimum": 0,
                },
            },
            "required": build_save_target_required_parameters(
                include_overwrite=True,
            ),
        },
        parameter_input_bindings=build_save_target_parameter_input_bindings(
            include_overwrite=True,
        ),
        capability_tags=("io.output", "inspection.result.persist", "json.save"),
    ),
    handler=_json_save_local_handler,
)
