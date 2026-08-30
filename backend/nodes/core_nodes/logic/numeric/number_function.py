"""常用单值与双值数值函数节点。"""

from __future__ import annotations

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
)
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


SUPPORTED_FUNCTIONS = {"abs", "round", "clamp", "min", "max"}
ROUNDING_MODES = {
    "half-even": ROUND_HALF_EVEN,
    "half-up": ROUND_HALF_UP,
    "toward-zero": ROUND_DOWN,
    "floor": ROUND_FLOOR,
    "ceiling": ROUND_CEILING,
}


def _number_function_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行受控数值函数。"""

    function_name = _require_choice(
        request.parameters.get("function", "abs"),
        field_name="function",
        supported_values=SUPPORTED_FUNCTIONS,
    )
    value = _read_number_input(request, "value")
    if function_name == "abs":
        result = abs(value)
    elif function_name == "round":
        result = _round_value(value, request=request)
    elif function_name == "clamp":
        minimum = require_finite_number(
            request.parameters.get("minimum"),
            field_name="minimum",
        )
        maximum = require_finite_number(
            request.parameters.get("maximum"),
            field_name="maximum",
        )
        if minimum > maximum:
            raise InvalidRequestError("Number Function 的 minimum 不能大于 maximum")
        result = min(max(value, minimum), maximum)
    else:
        other = _read_optional_other(request)
        result = min(value, other) if function_name == "min" else max(value, other)
    return {"value": build_value_payload(require_finite_number(result, field_name="result"))}


def _round_value(value: int | float, *, request: WorkflowNodeExecutionRequest) -> float:
    """按显式位数和舍入方式执行十进制舍入。"""

    raw_decimals = request.parameters.get("decimals", 0)
    if isinstance(raw_decimals, bool) or not isinstance(raw_decimals, int):
        raise InvalidRequestError("Number Function 的 decimals 必须是整数")
    if not -12 <= raw_decimals <= 12:
        raise InvalidRequestError("Number Function 的 decimals 必须在 -12 到 12 之间")
    rounding_mode = _require_choice(
        request.parameters.get("rounding_mode", "half-even"),
        field_name="rounding_mode",
        supported_values=set(ROUNDING_MODES),
    )
    quantizer = Decimal(1).scaleb(-raw_decimals)
    try:
        rounded = Decimal(str(value)).quantize(
            quantizer,
            rounding=ROUNDING_MODES[rounding_mode],
        )
    except InvalidOperation as error:
        raise InvalidRequestError("Number Function 无法舍入当前数值") from error
    return float(rounded)


def _read_optional_other(request: WorkflowNodeExecutionRequest) -> int | float:
    """读取 Min/Max 使用的第二个数值。"""

    if request.input_values.get("other") is not None:
        return _read_number_input(request, "other")
    if "other_value" not in request.parameters:
        raise InvalidRequestError("Min/Max 要求 Other 输入或 other_value 参数")
    return require_finite_number(
        request.parameters.get("other_value"),
        field_name="other_value",
    )


def _read_number_input(
    request: WorkflowNodeExecutionRequest,
    input_name: str,
) -> int | float:
    """从 value.v1 读取有限数值。"""

    raw_value = require_value_payload(
        request.input_values.get(input_name),
        field_name=input_name,
    )["value"]
    return require_finite_number(raw_value, field_name=input_name)


def _require_choice(
    raw_value: object,
    *,
    field_name: str,
    supported_values: set[str],
) -> str:
    """读取受控小写枚举。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in supported_values:
        raise InvalidRequestError(
            f"{field_name} 仅支持 {', '.join(sorted(supported_values))}"
        )
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.number-function",
        display_name="Number Function",
        category="core.logic.transform",
        description="执行 Abs、Round、Clamp、Min 或 Max，并拒绝 NaN/Inf。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(name="value", display_name="Value", payload_type_id="value.v1"),
            NodePortDefinition(
                name="other",
                display_name="Other",
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
                "function": {
                    "type": "string",
                    "enum": sorted(SUPPORTED_FUNCTIONS),
                    "default": "abs",
                    "title": "Function",
                },
                "decimals": {
                    "type": "integer",
                    "minimum": -12,
                    "maximum": 12,
                    "default": 0,
                },
                "rounding_mode": {
                    "type": "string",
                    "enum": sorted(ROUNDING_MODES),
                    "default": "half-even",
                },
                "minimum": {"type": "number", "default": 0.0},
                "maximum": {"type": "number", "default": 1.0},
                "other_value": {"type": "number", "default": 0.0},
            },
            "required": ["function"],
        },
        capability_tags=("logic.numeric", "number.function", "execution.pure"),
    ),
    handler=_number_function_handler,
)
