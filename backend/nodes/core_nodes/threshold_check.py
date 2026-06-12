"""工业阈值判断节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import (
    build_boolean_payload,
    build_value_payload,
    compare_values,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "threshold-check"


def _threshold_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对单个数值执行工业语义阈值判断。"""

    value_payload = require_value_payload(request.input_values.get("value"), field_name="value")
    measured_value = _require_numeric_value(value_payload["value"], field_name="value")
    operator = _read_operator(request.parameters.get("operator"))
    threshold_value = _require_numeric_parameter(request.parameters.get("threshold"), field_name="threshold")
    passed = compare_values(left_value=measured_value, right_value=threshold_value, operator=operator)
    return {
        "result": build_boolean_payload(passed),
        "metrics": build_value_payload(
            {
                "value": measured_value,
                "operator": operator,
                "threshold": threshold_value,
                "result": passed,
            }
        ),
    }


def _read_operator(raw_value: object) -> str:
    """读取比较运算符。"""

    if raw_value is None:
        return "ge"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 operator 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"eq", "ne", "gt", "ge", "lt", "le", "=", "!=", ">", ">=", "<", "<="}:
        raise InvalidRequestError(f"{NODE_NAME} 节点不支持指定 operator", details={"operator": raw_value})
    return normalized_value


def _require_numeric_parameter(raw_value: object, *, field_name: str) -> float:
    """读取数值型参数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是数值")
    return float(raw_value)


def _require_numeric_value(raw_value: object, *, field_name: str) -> float:
    """读取 value.v1 内的数值。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 {field_name} 必须是数值")
    return float(raw_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.rule.threshold-check",
        display_name="Threshold Check",
        category="rule.condition",
        description="对单个数值执行阈值判断，适合面积、覆盖率、偏移量、分数等工业规则计算。",
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
                "operator": {
                    "type": "string",
                    "title": "运算符",
                    "enum": ["ge", "gt", "le", "lt", "eq", "ne", ">=", ">", "<=", "<", "=", "!="],
                    "default": "ge",
                },
                "threshold": {
                    "type": "number",
                    "title": "阈值",
                },
            },
            "required": ["threshold"],
        },
        capability_tags=("rule.condition", "inspection.threshold", "inspection.rule"),
    ),
    handler=_threshold_check_handler,
)
