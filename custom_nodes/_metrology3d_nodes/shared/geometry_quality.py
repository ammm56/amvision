"""几何质量仅组合既有数值和限值结果，不新增比较算法。"""

from backend.contracts.workflows.geometry3d_observations import GeometryQuality
from backend.contracts.workflows.metrology import NumericItem, NumericTable
from backend.nodes.core_nodes.support.measurement import check_limits


def geometry_quality(observation_id, values, policy, *, reason):
    """values 为稳定指标 ID 到 (值, 单位) 的映射，未知量保留 null。"""
    table = NumericTable(
        observation_id=observation_id,
        items=tuple(
            NumericItem(
                item_id=name,
                value=value,
                unit=unit,
                valid=value is not None,
                reason=None if value is not None else reason,
            )
            for name, (value, unit) in values.items()
        ),
    )
    checked = check_limits(table, policy.rules)
    required = [item for item in checked["items"] if item["required"]]
    return GeometryQuality(
        metrics=table,
        checks=checked["items"],
        usable=bool(required)
        and all(item["valid"] and item["passed"] for item in required),
    )
