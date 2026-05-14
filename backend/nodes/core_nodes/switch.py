"""多分支选择逻辑节点。"""

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
    require_value_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _switch_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按顺序匹配 case 列表并返回第一个命中的结果值。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：选中的 value payload 和是否命中的布尔结果。
    """

    target_value = require_value_payload(request.input_values.get("value"), field_name="value")["value"]
    raw_case_payloads = request.input_values.get("cases")
    if not isinstance(raw_case_payloads, tuple) or not raw_case_payloads:
        raise InvalidRequestError(
            "switch 节点要求 cases 输入至少提供一个 case payload",
            details={"node_id": request.node_id},
        )

    for case_index, case_payload in enumerate(raw_case_payloads, start=1):
        case_value = require_value_payload(case_payload, field_name=f"cases[{case_index}]")["value"]
        if not isinstance(case_value, dict):
            raise InvalidRequestError(
                "switch 节点要求每个 case payload 的 value 都必须是对象",
                details={"node_id": request.node_id, "case_index": case_index},
            )
        if "when" not in case_value:
            raise InvalidRequestError(
                "switch 节点要求每个 case 对象都包含 when 字段",
                details={"node_id": request.node_id, "case_index": case_index},
            )
        if target_value == case_value.get("when"):
            return {
                "value": build_value_payload(case_value.get("then")),
                "matched": build_boolean_payload(True),
            }

    default_input_payload = request.input_values.get("default")
    if default_input_payload is not None:
        return {
            "value": require_value_payload(default_input_payload, field_name="default"),
            "matched": build_boolean_payload(False),
        }
    if "default_value" in request.parameters:
        return {
            "value": build_value_payload(request.parameters.get("default_value")),
            "matched": build_boolean_payload(False),
        }
    raise InvalidRequestError(
        "switch 节点未匹配到任何 case，且未提供默认值",
        details={"node_id": request.node_id, "value": target_value},
    )


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.switch",
        display_name="Switch",
        category="logic.branch",
        description="按输入值顺序匹配多个 case，并返回第一个命中的结果值。",
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
                multiple=True,
                description="每个 case 的 value 必须是包含 when 和 then 的对象。",
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
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "default_value": {},
            },
        },
        capability_tags=("logic.branch", "condition.switch"),
    ),
    handler=_switch_handler,
)