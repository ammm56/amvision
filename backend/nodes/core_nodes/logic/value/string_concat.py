"""通用字符串拼接节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """严格拼接左右两个字符串，不执行格式化或隐式类型转换。"""

    left = require_value_payload(
        request.input_values.get("left"),
        field_name="left",
    )["value"]
    right = require_value_payload(
        request.input_values.get("right"),
        field_name="right",
    )["value"]
    if not isinstance(left, str):
        raise InvalidRequestError("Concat Strings 的 left.value 必须是字符串")
    if not isinstance(right, str):
        raise InvalidRequestError("Concat Strings 的 right.value 必须是字符串")
    return {"value": build_value_payload(left + right)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.string-concat",
        display_name="Concat Strings",
        category="core.logic.transform",
        description="按 left、right 顺序严格拼接两个字符串，不解析占位符或执行隐式类型转换。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
        input_ports=(
            NodePortDefinition(
                name="left",
                display_name="Left",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="right",
                display_name="Right",
                payload_type_id="value.v1",
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
            "properties": {},
            "additionalProperties": False,
        },
        capability_tags=("logic.text", "string.concat", "execution.pure"),
    ),
    handler=_handler,
)
