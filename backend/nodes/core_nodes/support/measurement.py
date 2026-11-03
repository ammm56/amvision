"""通用数值表的限值校验与显示适配，不依赖行业节点或 OpenCV。"""

from backend.contracts.workflows.inspection import LimitCheckSummary
from backend.contracts.workflows.metrology import LimitRule, NumericTable, unique_ids


def check_limit_items(table: NumericTable, rules: tuple[LimitRule, ...]) -> list[dict]:
    """共享逐项数值比较，不在几何质量路径引入产品判定语义。"""
    unique_ids([rule.item_id for rule in rules], "rules")
    if len(rules) > 8192:
        raise ValueError("规则数量超过 8192")
    values = {item.item_id: item for item in table.items}
    results = []
    for rule in rules:
        if not rule.enabled:
            continue
        item = values.get(rule.item_id)
        reason = None
        if item is None:
            reason = "missing_value"
        elif not item.valid:
            reason = item.reason
        elif item.unit != rule.unit:
            reason = "unit_mismatch"
        else:
            reason = rule.violation_reason(item.value)
        results.append(
            {
                "item_id": rule.item_id,
                "required": rule.required,
                "passed": reason is None,
                "valid": item is not None and item.valid and item.unit == rule.unit,
                "value": item.value
                if item is not None and item.unit == rule.unit
                else None,
                "unit": rule.unit,
                "lower": rule.lower,
                "upper": rule.upper,
                "include_lower": rule.include_lower,
                "include_upper": rule.include_upper,
                "actual_unit": item.unit if item is not None else None,
                "reason": reason,
            }
        )
    return results


def check_limits(table: NumericTable, rules: tuple[LimitRule, ...]) -> dict:
    """按已配置必检集合汇总三态；INVALID 优先且保留已有 NG 项。"""
    items = [
        {
            **item,
            "state": "invalid"
            if not item["valid"]
            else "ok"
            if item["passed"]
            else "ng",
        }
        for item in check_limit_items(table, rules)
    ]
    required = [item for item in items if item["required"]]
    counts = {
        state: sum(item["state"] == state for item in required)
        for state in ("ok", "ng", "invalid")
    }
    reason = (
        "no_required_checks"
        if not required
        else "required_invalid"
        if counts["invalid"]
        else "required_out_of_limits"
        if counts["ng"]
        else None
    )
    state = (
        "invalid"
        if not required or counts["invalid"]
        else "ng"
        if counts["ng"]
        else "ok"
    )
    return LimitCheckSummary.model_validate(
        {
            "format_id": "amvision.limit-check.v1",
            "observation_id": table.observation_id,
            "passed": state == "ok",
            "state": state,
            "reason": reason,
            "items": items,
            "required_count": len(required),
            "required_ok_count": counts["ok"],
            "required_ng_count": counts["ng"],
            "required_invalid_count": counts["invalid"],
            "optional_count": len(items) - len(required),
        }
    ).model_dump(mode="json")


def numeric_table_to_value(table: NumericTable) -> dict:
    """显式转换成可供 Extract Value Field/Value Display 使用的普通值对象。"""
    return {
        "observation_id": table.observation_id,
        "values": {item.item_id: item.value for item in table.items},
        "items": [item.model_dump(mode="json") for item in table.items],
    }
