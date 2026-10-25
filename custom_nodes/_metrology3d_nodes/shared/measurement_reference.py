"""在既有实测覆盖检查之后处理显式基准延伸，不修改被测表面规则。"""

import numpy as np

from backend.contracts.workflows.measurement3d_parameters import ExtendedReference
from backend.contracts.workflows.measurement3d_reference import ReferenceExtension
from custom_nodes._metrology3d_nodes.shared.fit_plane import _positions, _rows
from custom_nodes._metrology3d_nodes.shared.measurement_support import (
    _tangent,
    plane_coverage,
)


def reference_coverage(runtime, feature, settings, *, cancel):
    """最近距离在完整有限基准支持上计算，局部支持半径不充当延伸上限。"""
    side, point = plane_coverage(runtime, feature, settings, "reference", cancel=cancel)
    policy = settings.reference_policy
    if not isinstance(policy, ExtendedReference):
        return side, point
    state, distance, nearest_point, source_index = "unavailable", None, None, None
    origin = None
    projected_point, datum_point = None, None
    if side.coverage is not None and side.coverage.covered:
        state, distance, origin = "covered", 0.0, "supported"
    elif point is not None:
        cloud = feature.support
        basis = _tangent(np.asarray(feature.geometry.normal))
        nearest = np.inf
        rows = _rows(runtime, cloud)
        with runtime.borrow(cloud) as view, np.errstate(over="raise", invalid="raise"):
            for start in range(0, cloud.point_count, rows):
                cancel()
                stop = min(start + rows, cloud.point_count)
                positions = _positions(view, start, stop)
                projected = (positions - point) @ basis
                distances = np.hypot(projected[:, 0], projected[:, 1])
                local_min = float(distances.min())
                if local_min <= nearest:
                    candidates = np.flatnonzero(distances == local_min)
                    indices = view.source_indices(start, stop).reshape(-1)
                    chosen = int(candidates[np.argmin(indices[candidates])])
                    index = int(indices[chosen])
                    if (
                        local_min < nearest
                        or source_index is None
                        or index < source_index
                    ):
                        nearest = local_min
                        nearest_point = tuple(float(x) for x in positions[chosen])
                        source_index = index
            if nearest_point is not None:
                distance = nearest
                state = (
                    "used"
                    if distance <= policy.max_extension_distance
                    else "limit-exceeded"
                )
                origin = "datum-extension" if state == "used" else None
                normal = np.asarray(feature.geometry.normal)
                projected_point = tuple(
                    float(x)
                    for x in (
                        np.asarray(nearest_point)
                        - np.dot(np.asarray(nearest_point) - point, normal) * normal
                    )
                )
                datum_point = tuple(float(x) for x in point)
    cancel()
    extension = ReferenceExtension(
        state=state,
        used_extension=state == "used",
        distance=distance,
        max_distance=policy.max_extension_distance,
        nearest_support_point=nearest_point,
        projected_support_point=projected_point,
        datum_point=datum_point,
        source_index=source_index,
        endpoint_origin=origin,
    )
    return side.model_copy(update={"extension": extension}), point
