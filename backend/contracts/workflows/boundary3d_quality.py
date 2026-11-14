"""边界指标的固定字段和单位；限值判定仍由既有比较器负责。"""

from pydantic import Field
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.geometry3d_quality import GeometryQuality


class SegmentQuality(Contract):
    """每个实测段独立质量，由所有边界方法共同使用。"""

    segment_id: Identifier
    group_id: Identifier | None = Field(default=None, exclude_if=lambda v: v is None)
    quality: GeometryQuality


def boundary_metric_units(kind, unit):
    """返回各方法实际公开的完整指标集合。"""
    if kind in ("height-jump", "normal-crease"):
        result = dict(support_count="1", length=unit, max_pair_distance=unit)
        if kind == "height-jump":
            result["max_planar_gap"] = unit
        return result
    if kind in ("boundary", "visible-envelope"):
        result = dict(
            input_count="1",
            surface_point_count="1",
            face_count="1",
            candidate_count="1",
            support_count="1",
            length=unit,
        )
        if kind == "visible-envelope":
            result.update(
                profile_coverage="1",
                estimated_fraction="1",
                missing_neighbor_fraction="1",
                profile_max_gap=unit,
                profile_max_jump=unit,
                max_cell_span=unit,
                added_cell_count="1",
            )
        return result
    result = dict(
        support_count="1", plane_max_residual=unit, rms=unit, max_residual=unit
    )
    if kind == "line":
        result.update(span=unit, direction_gap="1", max_gap=unit)
    elif kind == "circle":
        result.update(jacobian_ratio="1", angular_coverage="rad", max_gap="rad")
        result.update(
            weighted_rms=unit,
            inlier_fraction="1",
            occupied_sector_count="1",
            sector_coverage="1",
            target_max_gap="rad",
            inlier_angular_coverage="rad",
            inlier_max_gap="rad",
            inlier_jacobian_ratio="1",
        )
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
            and item.item_id
            in (
                "direction_gap",
                "jacobian_ratio",
                "profile_coverage",
                "estimated_fraction",
                "missing_neighbor_fraction",
                "inlier_fraction",
                "sector_coverage",
                "inlier_jacobian_ratio",
            )
            and item.value > 1
        ):
            raise ValueError("边界比率超过范围")
