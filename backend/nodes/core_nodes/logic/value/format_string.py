"""受限占位符字符串格式化节点。"""

from __future__ import annotations

import re
from string import Formatter

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


_FIELD_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FORMATTER = Formatter()


def _format_string_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用受限命名占位符格式化字符串。"""

    template = _read_template(request)
    values_payload = require_value_payload(
        request.input_values.get("values"),
        field_name="values",
    )["value"]
    if not isinstance(values_payload, dict):
        raise InvalidRequestError("Format String 的 values.value 必须是对象")
    result_parts: list[str] = []
    try:
        parsed_parts = tuple(_FORMATTER.parse(template))
    except ValueError as error:
        raise InvalidRequestError("Format String 的 template 格式无效") from error
    for literal_text, field_name, format_spec, conversion in parsed_parts:
        result_parts.append(literal_text)
        if field_name is None:
            continue
        if not _FIELD_NAME_PATTERN.fullmatch(field_name):
            raise InvalidRequestError("Format String 只允许简单命名占位符")
        if conversion is not None:
            raise InvalidRequestError("Format String 不允许 !r、!s 等转换标记")
        if "{" in format_spec or "}" in format_spec:
            raise InvalidRequestError("Format String 的 format spec 不允许嵌套占位符")
        if field_name not in values_payload:
            raise InvalidRequestError(
                "Format String 缺少占位符值",
                details={"field_name": field_name},
            )
        try:
            result_parts.append(format(values_payload[field_name], format_spec))
        except (TypeError, ValueError) as error:
            raise InvalidRequestError(
                "Format String 无法按 format spec 格式化字段",
                details={"field_name": field_name, "format_spec": format_spec},
            ) from error
    return {"value": build_value_payload("".join(result_parts))}


def _read_template(request: WorkflowNodeExecutionRequest) -> str:
    """读取统一动态参数解析后的格式模板。"""

    raw_template = request.parameters.get("template", "{value}")
    if not isinstance(raw_template, str):
        raise InvalidRequestError("Format String 的 template 必须是字符串")
    return raw_template


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.format-string",
        display_name="Format String",
        category="core.logic.transform",
        description="使用简单命名占位符格式化文本，不执行表达式或任意代码。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="template",
                display_name="Template",
                payload_type_id="value.v1",
                required=False,
            ),
            NodePortDefinition(name="values", display_name="Values", payload_type_id="value.v1"),
        ),
        output_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "default": "{value}",
                    "title": "Template",
                }
            },
            "additionalProperties": False,
        },
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="template",
                input_port_name="template",
            ),
        ),
        capability_tags=("logic.text", "string.format", "execution.pure"),
    ),
    handler=_format_string_handler,
)
