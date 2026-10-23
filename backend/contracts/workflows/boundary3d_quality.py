"""边界指标的固定字段和单位；限值判定仍由既有比较器负责。"""


def boundary_metric_units(kind, unit):
    """返回各方法实际公开的完整指标集合。"""
    if kind == "boundary":
        return dict(
            input_count="1",
            surface_point_count="1",
            face_count="1",
            candidate_count="1",
            support_count="1",
            length=unit,
        )
    result = dict(
        support_count="1", plane_max_residual=unit, rms=unit, max_residual=unit
    )
    if kind == "line":
        result.update(span=unit, direction_gap="1", max_gap=unit)
    elif kind == "circle":
        result.update(jacobian_ratio="1", angular_coverage="rad", max_gap="rad")
    else:
        raise ValueError("未知边界指标类型")
    return result


def check_boundary_metrics(quality, kind, unit):
    """拒绝字段遗漏、单位错误、负残差或非整数计数。"""
    units = boundary_metric_units(kind, unit)
    if {item.item_id for item in quality.metrics.items} != set(units):
        raise ValueError("边界指标集合不完整")
    for item in quality.metrics.items:
        if item.unit != units[item.item_id] or (item.valid and item.value < 0):
            raise ValueError("边界指标单位或范围无效")
        if (
            item.valid
            and item.item_id.endswith("_count")
            and not item.value.is_integer()
        ):
            raise ValueError("边界计数必须为整数")
        if (
            item.valid
            and item.item_id in ("direction_gap", "jacobian_ratio")
            and item.value > 1
        ):
            raise ValueError("边界比率超过范围")
