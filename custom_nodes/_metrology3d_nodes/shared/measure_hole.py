"""孔/圆弧尺寸直接消费 CircleFeature，禁止重新拟合或静默重选支持。"""

import numpy as np

from backend.contracts.workflows.dimension3d_evidence import HoleGeometry
from custom_nodes._metrology3d_nodes.shared.dimension_runtime import (
    dimension_result,
    dimension_support,
    select_features,
)


def measure_hole(runtime, groups, parameters, *, cancel):
    """所有启用量共用同一圆及质量，直径辅助端点是构造点。"""
    feature = select_features(
        runtime, groups, parameters, [parameters.feature_id], "circle"
    )[0]
    support = dimension_support(
        runtime, feature.support, "source", feature=feature, cancel=cancel
    )
    reason, stage = feature.reason, "input"
    geometry = None
    values = {}
    role_usable = False
    if feature.valid:
        segments = support.topology.segments
        role_usable = (
            (len(segments) == 1 and segments[0].closed and segments[0].role == "inner")
            if parameters.target_kind == "closed-hole"
            else all(not s.closed and s.role == "open" for s in segments)
        )
        if not role_usable:
            reason, stage = "invalid_boundary_role", "support"
        else:
            model = feature.geometry
            direction = np.asarray(parameters.display_direction)
            if abs(float(direction @ model.normal)) > 1e-8:
                reason, stage = "display_direction_out_of_plane", "geometry"
            else:
                center = np.asarray(model.center)
                geometry = HoleGeometry(
                    circle=model,
                    display_direction=direction,
                    diameter_endpoints=[
                        center - model.radius * direction,
                        center + model.radius * direction,
                    ],
                )
                values = dict(
                    diameter=2 * model.radius,
                    center_x=model.center[0],
                    center_y=model.center[1],
                    center_z=model.center[2],
                )
    # 保留原圆全部质量指标，测量节点只附加角色条件和几何可用性。
    metrics = {i.item_id: (i.value, i.unit) for i in feature.quality.metrics.items}
    metrics["role_usable"] = (int(role_usable), "1")
    cancel()
    return dimension_result(
        "measure-hole",
        parameters,
        groups[0].observation_id,
        (support,),
        geometry=geometry,
        metrics=metrics,
        values=values,
        reason=reason,
        stage=stage,
        feature_id=feature.feature_id if reason else None,
    )
