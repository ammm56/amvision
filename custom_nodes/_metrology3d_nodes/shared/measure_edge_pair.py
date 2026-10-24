"""既有有限直线的解析测距；不重新拟合，不跨缺口或延长支持。"""

import numpy as np

from backend.contracts.workflows.dimension3d_evidence import EdgePairGeometry
from custom_nodes._metrology3d_nodes.shared.dimension_runtime import (
    dimension_result,
    dimension_support,
    select_features,
)


def _intersection(feature, parameters):
    """先核对三维共面，再解二维方程，并回到三维检查残差。"""
    evaluation = parameters.evaluation
    rotation = np.asarray(evaluation.rotation)
    basis, normal = rotation[:, :2], rotation[:, 2]
    source_plane = feature.method.parameters.evaluation
    source_normal = np.asarray(source_plane.rotation)[:, 2]
    angle = float(
        np.arctan2(
            np.linalg.norm(np.cross(normal, source_normal)), abs(normal @ source_normal)
        )
    )
    offset = abs(float((np.asarray(source_plane.origin) - evaluation.origin) @ normal))
    a, d = np.asarray(feature.geometry.origin), np.asarray(feature.geometry.direction)
    p, v = np.asarray(parameters.query_position), np.asarray(parameters.direction)
    metrics = dict(
        plane_angle=angle,
        plane_distance=offset,
        crossing_sine=None,
        intersection_residual=None,
        supported=0,
    )
    # 还检查实际支持两端，避免只检查原点却接受面外长线。
    for interval in feature.intervals:
        for s in (interval.start, interval.end):
            offset = max(offset, abs(float((a - evaluation.origin + s * d) @ normal)))
    metrics["plane_distance"] = offset
    if (
        angle > parameters.max_plane_angle_radians
        or offset > parameters.max_plane_distance
    ):
        return "non_coplanar", metrics, None
    dv, vv = d @ basis, v @ basis
    sine = (
        abs(float(vv[0] * dv[1] - vv[1] * dv[0]))
        / float(np.linalg.norm(dv) * np.linalg.norm(vv))
        if np.linalg.norm(dv)
        else 0.0
    )
    metrics["crossing_sine"] = min(1.0, sine)
    if sine < parameters.min_crossing_sine:
        return "ill_conditioned_intersection", metrics, None
    t, s = np.linalg.solve(np.column_stack((vv, -dv)), (a - p) @ basis)
    endpoint = p + t * v
    residual = float(np.linalg.norm((a - p) + s * d - t * v))
    metrics["intersection_residual"] = residual
    if residual > parameters.max_plane_distance:
        return "non_coplanar", metrics, None
    interval = next((i for i in feature.intervals if i.start <= s <= i.end), None)
    if interval is None:
        low, high = (
            min(i.start for i in feature.intervals),
            max(i.end for i in feature.intervals),
        )
        return "support_gap" if low <= s <= high else "outside_support", metrics, None
    metrics["supported"] = 1
    return None, metrics, (float(t), float(s), tuple(endpoint), interval.segment_id)


def measure_edge_pair(runtime, groups, parameters, *, cancel):
    """两个输入角色保持稳定，有效零距离与缺测严格分开。"""
    features = select_features(
        runtime,
        groups,
        parameters,
        [parameters.reference_feature_id, parameters.target_feature_id],
        "line",
    )
    support = tuple(
        dimension_support(runtime, f.support, role, feature=f, cancel=cancel)
        for f, role in zip(features, ("reference", "target"))
    )
    metrics, hits, reason, stage, failed = {}, [], None, "geometry", None
    for feature, side in zip(features, support):
        cancel()
        missing = dict(
            plane_angle=None,
            plane_distance=None,
            crossing_sine=None,
            intersection_residual=None,
            supported=0,
        )
        error, local, hit = (
            _intersection(feature, parameters)
            if feature.valid
            else (feature.reason, missing, None)
        )
        for name, value in local.items():
            unit = (
                parameters.length_unit
                if name in {"plane_distance", "intersection_residual"}
                else "rad"
                if name == "plane_angle"
                else "1"
            )
            metrics[f"{side.role}_{name}"] = (value, unit)
        metrics[f"{side.role}_count"] = (side.point_count, "1")
        hits.append(hit)
        if error and reason is None:
            reason, failed = error, feature.feature_id
            stage = (
                "input"
                if not feature.valid
                else "support"
                if error in {"support_gap", "outside_support"}
                else "geometry"
            )
    geometry = None
    if reason is None:
        a, b = (f.geometry for f in features)
        delta = np.asarray(b.origin) - a.origin
        cross = np.cross(a.direction, b.direction)
        offset = np.linalg.norm(np.cross(delta, a.direction))
        numeric = 32 * np.finfo(float).eps
        if np.linalg.norm(cross) <= numeric and offset <= numeric * max(
            1.0, float(np.linalg.norm(delta))
        ):
            reason = "coincident_edges"
        else:
            geometry = EdgePairGeometry(
                query_position=parameters.query_position,
                direction=parameters.direction,
                endpoints=[h[2] for h in hits],
                line_parameters=[h[1] for h in hits],
                query_parameters=[h[0] for h in hits],
                segment_ids=[h[3] for h in hits],
                signed_distance=hits[1][0] - hits[0][0],
            )
    value = (
        None
        if geometry is None
        else geometry.signed_distance
        if parameters.value_mode == "signed"
        else abs(geometry.signed_distance)
    )
    cancel()
    return dimension_result(
        "measure-edge-pair",
        parameters,
        groups[0].observation_id,
        support,
        geometry=geometry,
        metrics=metrics,
        values={"distance": value},
        reason=reason,
        stage=stage,
        feature_id=failed,
    )
