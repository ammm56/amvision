"""在既有实测覆盖检查之后处理显式基准延伸，不修改被测表面规则。"""

from dataclasses import replace

import numpy as np

from backend.contracts.workflows.measurement3d_parameters import ExtendedReference
from backend.contracts.workflows.measurement3d_reference import ReferenceExtension
from custom_nodes.metrology3d_nodes.shared.measurement_support import (
    plane_coverage,
)


def reference_coverage(runtime, feature, settings, *, cancel):
    """最近距离在完整有限基准支持上计算，局部支持半径不充当延伸上限。"""
    policy = settings.reference_policy
    scan = plane_coverage(
        runtime,
        feature,
        settings,
        "reference",
        cancel=cancel,
        capture_nearest=isinstance(policy, ExtendedReference),
    )
    side, point = scan.support, scan.point
    if not isinstance(policy, ExtendedReference):
        return scan
    state, distance, nearest_point, source_index = "unavailable", None, None, None
    origin = None
    projected_point, datum_point = None, None
    if side.coverage is not None and side.coverage.covered:
        state, distance, origin = "covered", 0.0, "supported"
    elif point is not None and scan.nearest is not None:
        with np.errstate(over="raise", invalid="raise"):
            distance = scan.nearest.distance
            nearest_point, source_index = scan.nearest.point, scan.nearest.source_index
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
    return replace(scan, support=side.model_copy(update={"extension": extension}))
