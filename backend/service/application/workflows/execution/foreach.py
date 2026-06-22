"""workflow for-each 节点解析和结果归一化辅助函数。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import WorkflowGraphNode
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError


def read_for_each_body_node_ids(
    *,
    node: WorkflowGraphNode,
    node_instances: dict[str, WorkflowGraphNode],
) -> tuple[str, ...]:
    """读取并校验单个 for-each 的循环体节点列表。"""

    raw_body_node_ids = node.parameters.get("body_node_ids")
    if not isinstance(raw_body_node_ids, list) or not raw_body_node_ids:
        raise InvalidRequestError(
            "for-each 节点要求 body_node_ids 必须是非空数组",
            details={"node_id": node.node_id},
        )
    body_node_ids: list[str] = []
    for raw_node_id in raw_body_node_ids:
        if not isinstance(raw_node_id, str) or not raw_node_id.strip():
            raise InvalidRequestError(
                "for-each 的 body_node_ids 每一项都必须是非空字符串",
                details={"node_id": node.node_id},
            )
        node_id = raw_node_id.strip()
        if node_id == node.node_id:
            raise InvalidRequestError(
                "for-each 不能把自身声明为循环体节点",
                details={"node_id": node.node_id},
            )
        if node_id not in node_instances:
            raise InvalidRequestError(
                "for-each 的 body_node_ids 引用了不存在的节点",
                details={"node_id": node.node_id, "body_node_id": node_id},
            )
        if node_id in body_node_ids:
            raise InvalidRequestError(
                "for-each 的 body_node_ids 不能包含重复节点",
                details={"node_id": node.node_id, "body_node_id": node_id},
            )
        body_node_ids.append(node_id)
    return tuple(body_node_ids)


def read_for_each_text_parameter(
    *,
    node: WorkflowGraphNode,
    parameter_name: str,
) -> str:
    """读取 for-each 必填字符串参数。"""

    raw_value = node.parameters.get(parameter_name)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            f"for-each 节点要求 {parameter_name} 必须是非空字符串",
            details={"node_id": node.node_id, "parameter_name": parameter_name},
        )
    return raw_value.strip()


def read_optional_for_each_text_parameter(
    *,
    node: WorkflowGraphNode,
    parameter_name: str,
    default: str,
) -> str:
    """读取 for-each 可选字符串参数。"""

    raw_value = node.parameters.get(parameter_name)
    if raw_value is None:
        return default
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            f"for-each 节点要求 {parameter_name} 必须是非空字符串",
            details={"node_id": node.node_id, "parameter_name": parameter_name},
        )
    return raw_value.strip()


def require_for_each_items_value(
    *,
    node_id: str,
    items_payload: object,
) -> list[object]:
    """校验 for-each 的 items 输入必须是 value payload 且内部值为数组。"""

    if not isinstance(items_payload, dict) or "value" not in items_payload:
        raise InvalidRequestError(
            "for-each 节点要求 items 必须是 value payload",
            details={"node_id": node_id},
        )
    items_value = items_payload.get("value")
    if not isinstance(items_value, list):
        raise InvalidRequestError(
            "for-each 节点要求 items.value 必须是数组",
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
