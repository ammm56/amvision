"""偏差计算与证据读回共用原限值比较器及终态规则。"""

from backend.contracts.workflows.deviation3d_rows import (
    QUALITY_METRICS,
    DeviationStatus,
)
from backend.contracts.workflows.measurement3d_parameters import (
    directional_quality_policy,
)
from backend.contracts.workflows.metrology import NumericItem, NumericTable
from backend.nodes.core_nodes.support.measurement import check_limit_items


def deviation_quality(coverage, extension, parameters, observation_id):
    """覆盖不通过不得用延伸绕过；超限、缺支持与质量失败各有明确终态。"""
    extended = extension is not None and extension.state in {"used", "limit-exceeded"}
    rules = directional_quality_policy(
        parameters, parameters.length_unit, extension=extended
    ).rules
    values = {
        "reference_count": coverage.count,
        "reference_covered": int(coverage.covered),
        **{
            f"reference_{key}": getattr(coverage, key)
            for key in (
                "direction_cosine",
                "nearest_distance",
                "triangle_edge",
                "max_residual",
            )
        },
        "reference_extension_distance": extension.distance if extension else None,
    }
    checked = check_limit_items(
        NumericTable(
            observation_id=observation_id,
            items=tuple(
                NumericItem(
                    item_id=r.item_id,
                    unit=r.unit,
                    value=values[r.item_id],
                    valid=values[r.item_id] is not None,
                    reason=None if values[r.item_id] is not None else "missing_support",
                )
                for r in rules
            ),
        ),
        rules,
    )
    failed = sum(
        1 << QUALITY_METRICS.index(c["item_id"]) for c in checked if not c["passed"]
    )
    if extension is not None and extension.state == "limit-exceeded":
        state = DeviationStatus.EXTENSION_LIMIT_EXCEEDED
    elif not coverage.covered and not (
        extension is not None and extension.used_extension
    ):
        state = DeviationStatus.OUTSIDE_SUPPORT
    elif failed:
        state = DeviationStatus.SUPPORT_QUALITY_FAILED
    else:
        state = DeviationStatus.EXTENDED if extended else DeviationStatus.COVERED
    return state, failed
