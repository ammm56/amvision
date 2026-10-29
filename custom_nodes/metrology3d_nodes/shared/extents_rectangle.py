"""最小包络复用受控 trimesh，仅补物理尺度和完整并列集合解释。"""

from importlib.metadata import version

import numpy as np
from trimesh.bounds import oriented_bounds_2D

from backend.contracts.workflows.dimension3d_evidence import RectangleCandidates
from backend.service.application.errors import InvalidRequestError


def rectangle_axes(projected, mode, *, max_working_bytes, cancel):
    """返回确定的长轴代表；方向不唯一时不冒充唯一姿态。"""
    if version("trimesh") != "5.1.1+amvision.2":
        raise InvalidRequestError("最小矩形需要项目锁定的受控 trimesh")
    if projected.nbytes * 8 > max_working_bytes:
        raise InvalidRequestError("最小矩形局部规范化超过工作预算")
    center = (projected.min(axis=0) + projected.max(axis=0)) / 2
    scale = float(np.ptp(projected, axis=0).max())
    local = (projected - center) / scale
    cancel()
    _, _, candidates = oriented_bounds_2D(
        local,
        max_working_bytes=max_working_bytes - projected.nbytes - local.nbytes,
        cancel=cancel,
        area_abs_tolerance=mode.area_abs_tolerance / scale**2,
        area_rel_tolerance=mode.area_rel_tolerance,
        return_candidates=True,
    )
    sizes = np.sort(candidates["extents"], axis=1)[:, ::-1] * scale
    axes = candidates["axes"].copy()
    swap = candidates["extents"][:, 1] > candidates["extents"][:, 0]
    axes[swap] = np.column_stack((-axes[swap, 1], axes[swap, 0]))
    # 方向按模 pi 比较，符号/边枚举重复不会产生假歧义。
    angles = np.mod(np.arctan2(axes[:, 1], axes[:, 0]), np.pi)
    order = np.argsort(angles, kind="stable")
    sorted_angles = angles[order]
    targets = np.mod(sorted_angles + np.pi / 2, np.pi)
    nearest = np.searchsorted(sorted_angles, targets)
    spread = 0.0
    for shift in (-1, 0):
        cancel()
        difference = np.abs(
            sorted_angles - sorted_angles[(nearest + shift) % len(angles)]
        )
        spread = max(spread, float(np.minimum(difference, np.pi - difference).max()))
    ranges = tuple((float(sizes[:, i].min()), float(sizes[:, i].max())) for i in (0, 1))
    consistent = all(
        hi - lo <= max(mode.dimension_abs_tolerance, mode.dimension_rel_tolerance * hi)
        for lo, hi in ranges
    )
    square = ranges[0][1] - ranges[1][0] <= max(
        mode.dimension_abs_tolerance, mode.dimension_rel_tolerance * ranges[0][1]
    )
    summary = RectangleCandidates(
        hull_point_count=candidates["hull_point_count"],
        candidate_count=candidates["candidate_count"],
        tied_count=len(sizes),
        minimum_area=candidates["minimum_area"] * scale**2,
        length_range=ranges[0],
        width_range=ranges[1],
        dimensions_consistent=consistent,
        orientation_unique=consistent
        and not square
        and spread <= mode.orientation_tolerance_radians,
        orientation_spread_radians=spread,
    )
    theta = sorted_angles[0]
    axis = np.array([np.cos(theta), np.sin(theta)])
    return np.column_stack((axis, [-axis[1], axis[0]])), summary
