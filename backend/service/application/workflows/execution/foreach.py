"""workflow for-each 边界解析和结果归一化辅助函数。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import WorkflowGraphNode
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError

FOR_EACH_START_NODE_TYPE_ID = "core.logic.for-each-start"
FOR_EACH_END_NODE_TYPE_ID = "core.logic.for-each-end"
FOR_EACH_RESULT_INPUT_PORT = "result"
FOR_EACH_ITEM_OUTPUT_PORT = "item"
FOR_EACH_INDEX_OUTPUT_PORT = "index"
DEFAULT_FOR_EACH_ITEM_VARIABLE_NAME = "item"
DEFAULT_FOR_EACH_INDEX_VARIABLE_NAME = "index"


def is_for_each_boundary_node(node: WorkflowGraphNode) -> bool:
    """判断节点是否是 for-each 控制边界节点。"""

    return node.node_type_id in {FOR_EACH_START_NODE_TYPE_ID, FOR_EACH_END_NODE_TYPE_ID}


def require_for_each_items_value(
    *,
    node_id: str,
    items_payload: object,
) -> list[object]:
    """校验 for-each start 的 items 输入必须是 value payload 且内部值为数组。"""

    if not isinstance(items_payload, dict) or "value" not in items_payload:
        raise InvalidRequestError(
            "for-each start 节点要求 items 必须是 value payload",
            details={"node_id": node_id},
        )
    items_value = items_payload.get("value")
    if not isinstance(items_value, list):
        raise InvalidRequestError(
            "for-each start 节点要求 items.value 必须是数组",
            details={"node_id": node_id},
        )
    return list(items_value)


def read_for_each_loop_control_action(
    *,
    body_node: WorkflowGraphNode,
    raw_outputs: dict[str, object],
) -> str | None:
    """读取循环体节点请求的 break 或 continue 控制动作。"""

    if body_node.node_type_id != "core.logic.loop-control":
        return None
    activated_output = raw_outputs.get("activated")
    if not isinstance(activated_output, dict) or not isinstance(activated_output.get("value"), bool):
        raise ServiceConfigurationError(
            "loop-control 节点必须返回 boolean activated 输出",
            details={"node_id": body_node.node_id},
        )
    if not activated_output["value"]:
        return None
    action_output = raw_outputs.get("action")
    if not isinstance(action_output, dict) or not isinstance(action_output.get("value"), str):
        raise ServiceConfigurationError(
            "loop-control 节点必须返回字符串 action 输出",
            details={"node_id": body_node.node_id},
        )
    normalized_action = action_output["value"].strip().lower()
    if normalized_action not in {"break", "continue"}:
        raise ServiceConfigurationError(
            "loop-control 节点返回了不支持的 action",
            details={"node_id": body_node.node_id, "action": action_output["value"]},
        )
    return normalized_action


def normalize_for_each_collected_result(
    *,
    payload_type_id: str,
    output_value: object,
) -> object:
    """把常见 value-like 结果解包为更易用的列表元素。"""

    if payload_type_id in {"value.v1", "boolean.v1"} and isinstance(output_value, dict) and "value" in output_value:
        return output_value["value"]
    return output_value
