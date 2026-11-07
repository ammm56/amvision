"""高度跃变和法向折边共用完整双侧 ROI 拟面，不重复几何求解器。"""

import numpy as np

from custom_nodes.metrology3d_nodes.shared.plane_support import orthogonal_fit_blocks


def verify_edge_support(points, masks, settings, chunk, cancel):
    """两侧及联合 QR/SVD 保留全部支持；仅方法特有的方向条件分开。"""
    sides = tuple(points[masks[:, side]] for side in range(2))
    counts = tuple(len(p) for p in sides)
    unassigned = int((~masks.any(axis=1)).sum())
    overlap = int(masks.all(axis=1).sum())
    empty = (counts, unassigned, overlap, None, None, None, None)
    support = settings.support
    if overlap:
        return (*empty, "support_overlap")
    if len(points) and unassigned / len(points) > settings.max_unassigned_fraction:
        return (*empty, "unassigned_support")
    if min(counts) < support.min_points:
        return (*empty, "insufficient_support")

    def fit(values):
        """局部数组已在窗口准入中计费；算法仍为现有中心化 QR/SVD。"""
        return orthogonal_fit_blocks(
            len(values),
            lambda start, stop: values[start:stop],
            chunk_rows=chunk,
            cancel=cancel,
        )

    fitted = tuple(fit(p) for p in sides)
    models = tuple((f[0], f[1] if f[1][2] >= 0 else -f[1]) for f in fitted)
    rms = tuple(f[3] for f in fitted)
    maximum = tuple(f[4] for f in fitted)
    base = (counts, unassigned, overlap, rms, maximum, None, models)
    for _, normal, singular, error, largest in fitted:
        if singular[0] == 0 or (
            singular[1] / singular[0] < support.min_tangent_ratio
            or (singular[1] - singular[2]) / singular[0] < support.min_normal_gap
        ):
            return (*base, "degenerate_support")
        if (
            settings.kind == "height-jump"
            and abs(normal[2]) < settings.min_height_axis_cosine
        ):
            return (*base, "height_direction_ambiguous")
        if error > support.max_rms or largest > support.max_residual:
            return (*base, "side_quality_failed")
    if settings.kind == "normal-crease":
        angle = np.arccos(np.clip(abs(models[0][1] @ models[1][1]), 0, 1))
        if angle < settings.min_angle:
            return (*base, "normal_angle_insufficient")
    joint = fit(np.concatenate(sides))[3]
    return (
        counts,
        unassigned,
        overlap,
        rms,
        maximum,
        joint,
        models,
        "smooth_surface" if joint < support.min_joint_rms else None,
    )
