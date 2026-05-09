"""条件表达式类 core nodes 共享 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import compare_values, try_extract_value_by_path
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


def evaluate_condition_expression(
    *,
    root_value: object,
    condition: dict[str, object],
    node_id: str,
    context_label: str,
) -> bool:
    """递归计算条件表达式。

    参数：
    - root_value：当前条件表达式的根值。
    - condition：待计算的条件表达式对象。
    - node_id：当前节点实例 id。
    - context_label：当前条件表达式所属上下文标签。

    返回：
    - bool：条件表达式的计算结果。
    """

    operator = _require_condition_operator(
        condition.get("operator"),
        node_id=node_id,
        context_label=context_label,
    )
    if operator in {"and", "or"}:
        raw_conditions = condition.get("conditions")
        if not isinstance(raw_conditions, list) or not raw_conditions:
            raise InvalidRequestError(
                "条件表达式的 and/or 运算必须包含非空 conditions 数组",
                details={
                    "node_id": node_id,
                    "condition_context": context_label,
                    "operator": operator,
                },
            )
        child_results = [
            evaluate_condition_expression(
                root_value=root_value,
                condition=require_condition_expression(
                    raw_condition,
                    node_id=node_id,
                    context_label=f"{context_label}.conditions[{condition_index}]",
                ),
                node_id=node_id,
                context_label=f"{context_label}.conditions[{condition_index}]",
            )
            for condition_index, raw_condition in enumerate(raw_conditions)
        ]
        return all(child_results) if operator == "and" else any(child_results)

    if operator == "not":
        return not evaluate_condition_expression(
            root_value=root_value,
            condition=require_condition_expression(
                condition.get("condition"),
                node_id=node_id,
                context_label=f"{context_label}.condition",
            ),
            node_id=node_id,
            context_label=f"{context_label}.condition",
        )

    candidate_exists, candidate_value = _resolve_condition_candidate(
        root_value=root_value,
        condition=condition,
        node_id=node_id,
        context_label=context_label,
    )
    if operator == "exists":
        return candidate_exists and candidate_value is not None
    if operator == "missing":
        return (not candidate_exists) or candidate_value is None
    if not candidate_exists:
        return False
    if operator == "truthy":
        return bool(candidate_value)
    if operator == "falsy":
        return not bool(candidate_value)
    if operator in {"eq", "ne", "gt", "ge", "lt", "le", "=", "!=", ">", ">=", "<", "<="}:
        if "right" not in condition:
            raise InvalidRequestError(
                "条件表达式的比较运算必须提供 right 字段",
                details={
                    "node_id": node_id,
                    "condition_context": context_label,
                    "operator": operator,
                },
            )
        return compare_values(
            left_value=candidate_value,
            right_value=condition.get("right"),
            operator=operator,
        )
    if operator == "in":
        right_value = condition.get("right")
        if not isinstance(right_value, list):
            raise InvalidRequestError(
                "条件表达式的 in 运算要求 right 必须是数组",
                details={"node_id": node_id, "condition_context": context_label},
            )
        return candidate_value in right_value
    if operator == "contains":
        if "right" not in condition:
            raise InvalidRequestError(
                "条件表达式的 contains 运算必须提供 right 字段",
                details={"node_id": node_id, "condition_context": context_label},
            )
        return _evaluate_contains_condition(
            candidate_value=candidate_value,
            expected_value=condition.get("right"),
            node_id=node_id,
            context_label=context_label,
        )
    raise InvalidRequestError(
        "当前条件表达式不支持指定运算符",
        details={
            "node_id": node_id,
            "condition_context": context_label,
            "operator": operator,
        },
    )


def _require_condition_operator(raw_value: object, *, node_id: str, context_label: str) -> str:
    """读取并校验条件表达式运算符。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(
            "条件表达式要求 operator 必须是非空字符串",
            details={"node_id": node_id, "condition_context": context_label},
        )
    return raw_value.strip().lower()


def _resolve_condition_candidate(
    *,
    root_value: object,
    condition: dict[str, object],
    node_id: str,
    context_label: str,
) -> tuple[bool, object | None]:
    """根据 path 配置解析条件表达式当前要比较的值。"""

    raw_path = condition.get("path")
    if raw_path is None:
        return True, root_value
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise InvalidRequestError(
            "条件表达式的 path 必须是非空字符串",
            details={"node_id": node_id, "condition_context": context_label},
        )
    return try_extract_value_by_path(root=root_value, path=raw_path)


def _evaluate_contains_condition(
    *,
    candidate_value: object,
    expected_value: object,
    node_id: str,
    context_label: str,
) -> bool:
    """计算 contains 条件。"""

    if isinstance(candidate_value, list):
        return expected_value in candidate_value
    if isinstance(candidate_value, str):
        if not isinstance(expected_value, str):
            raise InvalidRequestError(
                "字符串 contains 条件要求 right 必须是字符串",
                details={"node_id": node_id, "condition_context": context_label},
            )
        return expected_value in candidate_value
    if isinstance(candidate_value, dict):
        if not isinstance(expected_value, str):
            raise InvalidRequestError(
                "对象 contains 条件要求 right 必须是字符串键名",
                details={"node_id": node_id, "condition_context": context_label},
            )
        return expected_value in candidate_value
    raise InvalidRequestError(
        "contains 条件只支持数组、字符串或对象",
        details={
            "node_id": node_id,
            "condition_context": context_label,
            "candidate_type": candidate_value.__class__.__name__,
        },
    )