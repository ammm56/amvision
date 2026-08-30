"""基础二元数值运算节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.logic.numeric._common import require_finite_number
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


SUPPORTED_OPERATIONS = {"add", "subtract", "multiply", "divide"}


def _number_operation_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行严格的二元数值运算。"""

    operation = _require_operation(request.parameters.get("operation", "add"))
    left = _read_number_input(request, input_name="left")
    right_payload = request.input_values.get("right")
    if right_payload is None:
        if "right_value" not in request.parameters:
            raise InvalidRequestError("Number Operation 要求 Right 输入或 right_value 参数")
        right = require_finite_number(
            request.parameters.get("right_value"),
            field_name="right_value",
        )
    else:
        right = _read_number_input(request, input_name="right")

    if operation == "add":
        result = left + right
    elif operation == "subtract":
        result = left - right
    elif operation == "multiply":
        result = left * right
    else:
        if right == 0.0:
            raise InvalidRequestError("Number Operation 不允许除数为 0")
        result = left / right
    return {"value": build_value_payload(require_finite_number(result, field_name="result"))}


def _read_number_input(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str,
) -> int | float:
    """从 value.v1 端口读取有限数值。"""

    value = require_value_payload(
        request.input_values.get(input_name),
        field_name=input_name,
    )["value"]
    return require_finite_number(value, field_name=input_name)


def _require_operation(raw_value: object) -> str:
    """读取受控运算名称。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError("Number Operation 的 operation 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in SUPPORTED_OPERATIONS:
        raise InvalidRequestError("operation 仅支持 add、subtract、multiply 或 divide")
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.number-operation",
        display_name="Number Operation",
        category="core.logic.transform",
        description="对两个有限数值执行 Add、Subtract、Multiply 或 Divide。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(name="left", display_name="Left", payload_type_id="value.v1"),
            NodePortDefinition(
                name="right",
                display_name="Right",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": sorted(SUPPORTED_OPERATIONS),
                    "default": "add",
                    "title": "Operation",
                },
                "right_value": {
                    "type": "number",
                    "default": 0.0,
                    "title": "Right Value",
                    "description": "Right 未连接时使用。",
                },
            },
            "required": ["operation"],
        },
        capability_tags=("logic.numeric", "number.operation", "execution.pure"),
    ),
    handler=_number_operation_handler,
)
