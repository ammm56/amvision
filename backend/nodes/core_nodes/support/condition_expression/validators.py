"""条件表达式校验 helper。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


def require_condition_expression(
    raw_condition: object,
    *,
    node_id: str,
    context_label: str,
) -> dict[str, object]:
    """校验条件表达式对象。

    参数：
    - raw_condition：待校验的条件表达式对象。
    - node_id：当前节点实例 id。
    - context_label：当前条件表达式所属上下文标签。

    返回：
    - dict[str, object]：规范化后的条件表达式对象。
    """

    if not isinstance(raw_condition, dict):
        raise InvalidRequestError(
            "条件表达式必须是对象",
            details={"node_id": node_id, "condition_context": context_label},
        )
    return dict(raw_condition)


def require_condition_operator(raw_value: object, *, node_id: str, context_label: str) -> str:
    """读取并校验条件表达式运算符。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            "条件表达式要求 operator 必须是非空字符串",
            details={"node_id": node_id, "condition_context": context_label},
        )
    return raw_value.strip().lower()
