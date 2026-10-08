"""通用数值表的限值校验与显示适配，不依赖行业节点或 OpenCV。"""

from backend.contracts.workflows.metrology import LimitRule, NumericTable, unique_ids


def check_limits(table: NumericTable, rules: tuple[LimitRule, ...]) -> dict:
    """按保存的必检集合检查数值，不从本次成功测量倒推必检项。"""
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
            value = item.value
            if rule.lower is not None and (
                value < rule.lower or (value == rule.lower and not rule.include_lower)
            ):
                reason = "below_lower_limit"
            if rule.upper is not None and (
                value > rule.upper or (value == rule.upper and not rule.include_upper)
            ):
                reason = "above_upper_limit"
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
    required = [item for item in results if item["required"]]
    passed = bool(required) and all(item["passed"] for item in required)
    return {
        "observation_id": table.observation_id,
        "passed": passed,
        "state": "ok" if passed else "ng",
        "reason": None if required else "no_required_checks",
        "items": results,
        "required_count": len(required),
        "passed_count": sum(item["passed"] for item in results),
    }


def numeric_table_to_value(table: NumericTable) -> dict:
    """显式转换成可供 Extract Value Field/Value Display 使用的普通值对象。"""
    return {
        "observation_id": table.observation_id,
        "values": {item.item_id: item.value for item in table.items},
        "items": [item.model_dump(mode="json") for item in table.items],
    }
