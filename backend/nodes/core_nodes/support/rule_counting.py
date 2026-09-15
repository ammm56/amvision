"""通用互斥规则计数，复用现有条件 DSL，不推断业务总数。"""

from collections.abc import Callable

from backend.nodes.core_nodes.support.condition_expression import (
    evaluate_condition_expression,
)
from backend.service.application.errors import InvalidRequestError

MAX_RULES = 64
MAX_CONDITION_DEPTH = 16


def validate_condition(condition: object, *, depth: int = 0) -> dict:
    """在处理任何数据前递归校验条件，包括空输入场景。"""
    if not isinstance(condition, dict) or depth > MAX_CONDITION_DEPTH:
        raise InvalidRequestError("条件必须为对象且嵌套不能超过 16 层")
    operator = str(condition.get("operator", "")).strip().lower()
    if operator in {"and", "or"}:
        children = condition.get("conditions")
        if not isinstance(children, list) or not 1 <= len(children) <= MAX_RULES:
            raise InvalidRequestError("and/or 需要 1–64 个条件")
        for child in children:
            validate_condition(child, depth=depth + 1)
    elif operator == "not":
        validate_condition(condition.get("condition"), depth=depth + 1)
    elif operator in {
        "exists",
        "missing",
        "truthy",
        "falsy",
        "eq",
        "ne",
        "gt",
        "ge",
        "lt",
        "le",
        "=",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "contains",
    }:
        path = condition.get("path")
        if path is not None and (not isinstance(path, str) or not path.strip()):
            raise InvalidRequestError("条件 path 必须为非空字符串")
        if (
            operator not in {"exists", "missing", "truthy", "falsy"}
            and "right" not in condition
        ):
            raise InvalidRequestError("比较条件缺少 right")
        if operator == "in" and not isinstance(condition["right"], list):
            raise InvalidRequestError("in 的 right 必须为数组")
    else:
        raise InvalidRequestError("不支持的条件 operator")
    return condition


def count_by_rules(
    items: list,
    rules: object,
    fallback_group: object = None,
    *,
    check_control: Callable[[], None] | None = None,
) -> dict:
    """计数列表中的独立单位；重叠命中失败，未匹配不隐式归组。"""
    if not isinstance(items, list):
        raise InvalidRequestError("items 必须为列表")
    if not isinstance(rules, list) or not 1 <= len(rules) <= MAX_RULES:
        raise InvalidRequestError("rules 必须包含 1–64 条规则")
    counts = {}
    for rule in rules:
        key = rule.get("key") if isinstance(rule, dict) else None
        if not isinstance(key, str) or not key.strip() or key in counts:
            raise InvalidRequestError("规则 key 必须非空且唯一")
        validate_condition(rule.get("condition"))
        counts[key] = 0
    if fallback_group is not None and (
        not isinstance(fallback_group, str) or fallback_group not in counts
    ):
        raise InvalidRequestError("fallback_group 必须指向已有规则")
    matched = fallback = unmatched = 0
    for index, item in enumerate(items):
        if check_control:
            check_control()
        hits = [
            r["key"]
            for r in rules
            if evaluate_condition_expression(
                root_value=item,
                condition=r["condition"],
                node_id="count-by-rules",
                context_label=f"items[{index}]",
            )
        ]
        if len(hits) > 1:
            raise InvalidRequestError(
                "同一项命中多个分组", details={"item_index": index, "groups": hits}
            )
        if hits:
            counts[hits[0]] += 1
            matched += 1
        elif fallback_group is not None:
            counts[fallback_group] += 1
            fallback += 1
        else:
            unmatched += 1
    return dict(
        counts=counts,
        input_count=len(items),
        matched_count=matched,
        fallback_count=fallback,
        unmatched_count=unmatched,
    )
