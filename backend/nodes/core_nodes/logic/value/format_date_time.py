"""通用日期时间格式化节点。"""

from __future__ import annotations

from datetime import datetime

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.date_time_template import render_date_time_template
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在当前节点执行时捕获一次本地时间并格式化为字符串。"""

    rendered = render_date_time_template(
        request.parameters.get("template", "{YYYYMMDDhhmmssSSS}"),
        current_time=datetime.now().astimezone(),
    )
    return {"value": build_value_payload(rendered)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.format-date-time",
        display_name="Format Date Time",
        category="core.logic.transform",
        description="按通用日期时间块格式化当前 runtime 主机本地时间；一次执行只捕获一个时间点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
        input_ports=(
            NodePortDefinition(
                name="template",
                display_name="Template",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "default": "{YYYYMMDDhhmmssSSS}",
                    "title": "Template",
                    "description": "通用日期时间格式，例如 {YYYY}-{MM}-{DD}_{hh}-{mm}-{ss}-{SSS}。",
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
        capability_tags=("logic.date-time", "string.format", "execution.pure"),
    ),
    handler=_handler,
)
