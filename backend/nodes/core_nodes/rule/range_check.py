"""工业范围判断节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import (
    build_boolean_payload,
    build_value_payload,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "range-check"


def _range_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对单个数值执行范围判断。"""

    value_payload = require_value_payload(request.input_values.get("value"), field_name="value")
    measured_value = _require_numeric_value(value_payload["value"])
    min_value = _read_optional_numeric_parameter(request.parameters.get("min_value"), field_name="min_value")
    max_value = _read_optional_numeric_parameter(request.parameters.get("max_value"), field_name="max_value")
    if min_value is None and max_value is None:
        raise InvalidRequestError(f"{NODE_NAME} 节点至少需要 min_value 或 max_value 之一")
    min_inclusive = _read_optional_bool(request.parameters.get("min_inclusive"), default=True)
    max_inclusive = _read_optional_bool(request.parameters.get("max_inclusive"), default=True)
    passed = _evaluate_range(
        measured_value=measured_value,
        min_value=min_value,
        max_value=max_value,
        min_inclusive=min_inclusive,
        max_inclusive=max_inclusive,
    )
    return {
        "result": build_boolean_payload(passed),
        "metrics": build_value_payload(
            {
                "value": measured_value,
                "min_value": min_value,
                "max_value": max_value,
                "min_inclusive": min_inclusive,
                "max_inclusive": max_inclusive,
                "result": passed,
            }
        ),
    }


def _evaluate_range(
    *,
    measured_value: float,
    min_value: float | None,
    max_value: float | None,
    min_inclusive: bool,
    max_inclusive: bool,
) -> bool:
    """执行范围判断。"""

    if min_value is not None:
        if min_inclusive:
            if measured_value < min_value:
                return False
        elif measured_value <= min_value:
            return False
    if max_value is not None:
        if max_inclusive:
            if measured_value > max_value:
                return False
        elif measured_value >= max_value:
            return False
    return True


def _require_numeric_value(raw_value: object) -> float:
    """读取 value.v1 内的数值。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 value 必须是数值")
    return float(raw_value)


def _read_optional_numeric_parameter(raw_value: object, *, field_name: str) -> float | None:
    """读取可选数值参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是数值")
    return float(raw_value)


def _read_optional_bool(raw_value: object, *, default: bool) -> bool:
    """读取可选布尔参数。"""

    if raw_value is None:
        return default
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{NODE_NAME} 节点的布尔参数必须是布尔值")
    return raw_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.rule.range-check",
        display_name="Range Check",
        category="rule.condition",
        description="对单个数值执行范围判断，适合面积、宽度、偏移量和覆盖率上下限规则。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "min_value": {"type": "number", "title": "最小值"},
                "max_value": {"type": "number", "title": "最大值"},
                "min_inclusive": {"type": "boolean", "title": "包含最小值", "default": True},
                "max_inclusive": {"type": "boolean", "title": "包含最大值", "default": True},
            },
        },
        capability_tags=("rule.condition", "inspection.range", "inspection.rule"),
    ),
    handler=_range_check_handler,
)
