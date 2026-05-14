"""循环控制逻辑节点。"""

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
    require_boolean_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def _loop_control_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """生成 for-each 可识别的 break/continue 控制信号。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 activated 与 action 的控制信号。
    """

    action = _require_loop_control_action(request.parameters.get("action"))
    condition_payload = request.input_values.get("condition")
    activated = True
    if condition_payload is not None:
        activated = require_boolean_payload(condition_payload, field_name="condition")["value"]
    return {
        "activated": build_boolean_payload(activated),
        "action": build_value_payload(action),
    }


def _require_loop_control_action(raw_value: object) -> str:
    """读取并校验循环控制动作。

    参数：
    - raw_value：待校验的动作值。

    返回：
    - str：规范化后的 break 或 continue。
    """

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("loop-control 节点要求 action 必须是非空字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"break", "continue"}:
        raise InvalidRequestError(
            "loop-control 节点仅支持 break 或 continue",
            details={"action": raw_value},
        )
    return normalized_value


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.logic.loop-control",
        display_name="Loop Control",
        category="logic.iteration",
        description="在 for-each 循环体中生成 break 或 continue 控制信号。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="condition",
                display_name="Condition",
                payload_type_id="boolean.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="activated",
                display_name="Activated",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="action",
                display_name="Action",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["break", "continue"]},
            },
            "required": ["action"],
        },
        capability_tags=("logic.iteration", "loop.control"),
    ),
    handler=_loop_control_handler,
)