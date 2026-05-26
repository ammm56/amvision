"""比较逻辑节点。"""

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
    compare_values,
    require_value_payload,
)
from backend.nodes.core_nodes._service_node_support import get_optional_dict_parameter, get_optional_str_parameter, require_str_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _compare_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按指定运算符比较左右值。"""

    operator = require_str_parameter(request, "operator")
    left_payload = require_value_payload(request.input_values.get("left"), field_name="left")
    right_input_payload = request.input_values.get("right")
    if right_input_payload is not None:
        right_value = require_value_payload(right_input_payload, field_name="right")["value"]
    else:
        if "right_value" not in request.parameters:
            raise InvalidRequestError(
                "compare 节点要求提供 right 输入或 right_value 参数",
                details={"node_id": request.node_id},
            )
        right_value = request.parameters.get("right_value")
    comparison_result = _compare_values(
        left_value=left_payload["value"],
        right_value=right_value,
        operator=operator,
    )
    return {"result": build_boolean_payload(comparison_result)}


def _compare_values(*, left_value: object, right_value: object, operator: str) -> bool:
    """执行最小比较语义。"""

    return compare_values(left_value=left_value, right_value=right_value, operator=operator)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.compare",
        display_name="Compare Values",
        category="logic.compare",
        description="支持 =、!=、>、>=、<、<= 的最小比较节点。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
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
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "x-amvision-ui": {
                "groups": {
                    "condition": {
                        "display_name": "Condition",
                        "order": 10,
                    }
                }
            },
            "properties": {
                "operator": {
                    "type": "string",
                    "title": "Operator",
                    "description": "比较左右值时使用的运算符。",
                    "enum": ["eq", "ne", "gt", "ge", "lt", "le", "=", "!=", ">", ">=", "<", "<="],
                    "default": "eq",
                    "x-amvision-ui": {
                        "group": "condition",
                        "order": 10,
                        "enum_labels": {
                            "eq": "Equals",
                            "ne": "Not Equals",
                            "gt": "Greater Than",
                            "ge": "Greater Than Or Equals",
                            "lt": "Less Than",
                            "le": "Less Than Or Equals",
                            "=": "Equals (=)",
                            "!=": "Not Equals (!=)",
                            ">": "Greater Than (>)",
                            ">=": "Greater Than Or Equals (>=)",
                            "<": "Less Than (<)",
                            "<=": "Less Than Or Equals (<=)",
                        },
                    },
                },
                "right_value": {
                    "title": "Right Value",
                    "description": "未连接 Right 输入端口时使用的比较目标。",
                    "x-amvision-ui": {
                        "group": "condition",
                        "order": 20,
                    },
                },
            },
            "required": ["operator"],
        },
        capability_tags=("logic.compare", "condition.evaluate"),
    ),
    handler=_compare_handler,
)