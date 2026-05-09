"""条件表达式匹配逻辑节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._collection_node_support import require_list_value
from backend.nodes.core_nodes._condition_expression_support import (
    evaluate_condition_expression,
    require_condition_expression,
)
from backend.nodes.core_nodes._logic_node_support import (
    build_boolean_payload,
    build_value_payload,
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _match_case_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按条件表达式列表顺序匹配第一个命中的 case。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：选中的值和是否命中的布尔结果。
    """

    target_value = require_value_payload(request.input_values.get("value"), field_name="value")["value"]
    case_list = require_list_value(
        request.input_values.get("cases"),
        field_name="cases",
        node_id=request.node_id,
    )
    for case_index, raw_case in enumerate(case_list):
        case_context = f"case[{case_index + 1}]"
        case_object = _require_case_object(raw_case=raw_case, node_id=request.node_id, case_context=case_context)
        if evaluate_condition_expression(
            root_value=target_value,
            condition=require_condition_expression(
                case_object.get("condition"),
                node_id=request.node_id,
                context_label=case_context,
            ),
            node_id=request.node_id,
            context_label=case_context,
        ):
            return {
                "value": build_value_payload(case_object.get("then")),
                "matched": build_boolean_payload(True),
                "matched_case_index": build_value_payload(case_index),
            }

    default_input_payload = request.input_values.get("default")
    if default_input_payload is not None:
        return {
            "value": require_value_payload(default_input_payload, field_name="default"),
            "matched": build_boolean_payload(False),
            "matched_case_index": build_value_payload(None),
        }
    if "default_value" in request.parameters:
        return {
            "value": build_value_payload(request.parameters.get("default_value")),
            "matched": build_boolean_payload(False),
            "matched_case_index": build_value_payload(None),
        }
    raise InvalidRequestError(
        "match-case 节点未命中任何 case，且未提供默认值",
        details={"node_id": request.node_id},
    )


def _require_case_object(*, raw_case: object, node_id: str, case_context: str) -> dict[str, object]:
    """校验单个 case 对象结构。"""

    if not isinstance(raw_case, dict):
        raise InvalidRequestError(
            "match-case 节点要求每个 case 都必须是对象",
            details={"node_id": node_id, "condition_context": case_context},
        )
    return dict(raw_case)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.match-case",
        display_name="Match Case",
        category="logic.branch",
        description="按条件表达式列表顺序匹配第一个命中的 case，支持比较、truthy、exists、in、contains 以及 and/or/not 组合。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="cases",
                display_name="Cases",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="default",
                display_name="Default",
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
            NodePortDefinition(
                name="matched",
                display_name="Matched",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="matched_case_index",
                display_name="Matched Case Index",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "default_value": {},
            },
        },
        capability_tags=("logic.branch", "condition.match-case"),
    ),
    handler=_match_case_handler,
)