"""完整候选格内的实测互近邻；不把拟面 ROI 边界作为实体边。"""

from enum import IntEnum

import numpy as np
from scipy.spatial import cKDTree

from backend.service.application.errors import InvalidRequestError


class PairStatus(IntEnum):
    """逐记录诊断；数值零仅表示已配对，不表示产品 OK。"""

    PAIRED = 0
    SUPPORT_INVALID = 1
    UNASSIGNED = 2
    SURFACE_AMBIGUOUS = 3
    OTHER_SIDE_MISSING = 4
    NEAREST_AMBIGUOUS = 5
    GAP_EXCEEDED = 6
    NOT_MUTUAL = 7
    PARTNER_AMBIGUOUS = 8
    NOT_HEIGHT_JUMP = 9
    NORMAL_INVALID = 10
    NEIGHBORHOOD_INCOMPLETE = 11
    PAIRING_CONFLICT = 12
    EDGE_ORDER_AMBIGUOUS = 13


def classify_points(points, origins, normals, max_residual, *, chunk_rows, cancel):
    """两种实测边共用完整残差归属；双重归属不能自动择近。"""
    cancel()
    count = len(points)
    if points.shape != (count, 3) or not np.isfinite(points).all():
        raise InvalidRequestError("实测配对位置不合法")
    # KDTree 平方距离与残差点积均必须保持有限，不能溢出后假装无邻点。
    with np.errstate(over="ignore", invalid="ignore"):
        span = np.ptp(points, axis=0) if count else np.zeros(3)
    if not np.isfinite(span).all() or np.any(span > np.sqrt(np.finfo(float).max) / 4):
        raise InvalidRequestError("实测配对跨度超出数值范围")
    belongs = np.empty((count, 2), dtype=bool)
    for start in range(0, count, chunk_rows):
        cancel()
        stop = min(count, start + chunk_rows)
        for side in range(2):
            with np.errstate(over="raise", invalid="raise"):
                residual = (points[start:stop] - origins[side]) @ normals[side]
            belongs[start:stop, side] = np.abs(residual) <= max_residual
    sides = np.full(count, 2, dtype="u1")
    sides[belongs[:, 0] & ~belongs[:, 1]] = 0
    sides[belongs[:, 1] & ~belongs[:, 0]] = 1
    sides[belongs.all(axis=1)] = 3
    status = np.full(count, PairStatus.UNASSIGNED, dtype="u1")
    status[sides == 3] = PairStatus.SURFACE_AMBIGUOUS
    return sides, status


def mutual_pairs(coordinates, sides, status, maximum, tolerance, *, chunk_rows, cancel):
    """共用精确互近邻；二维面内或三维空间由方法显式传入。"""
    count = len(coordinates)
    partner = np.full(count, -1, dtype="<i8")
    groups = tuple(np.flatnonzero(sides == side) for side in range(2))
    if not all(len(rows) for rows in groups):
        status[sides < 2] = PairStatus.OTHER_SIDE_MISSING
        return partner
    nearest = np.full(count, -1, dtype=np.int64)
    for side in range(2):
        cancel()
        query, other = groups[side], groups[1 - side]
        tree = cKDTree(coordinates[other], copy_data=True)
        cancel()
        for start in range(0, len(query), chunk_rows):
            cancel()
            rows = query[start : start + chunk_rows]
            distance, indices = tree.query(coordinates[rows], k=2, eps=0, workers=1)
            nearest[rows] = other[indices[:, 0]]
            ambiguous = distance[:, 1] - distance[:, 0] <= tolerance
            status[rows] = PairStatus.NOT_MUTUAL
            status[rows[distance[:, 0] > maximum]] = PairStatus.GAP_EXCEEDED
            status[rows[ambiguous]] = PairStatus.NEAREST_AMBIGUOUS
        del tree
    for row in groups[0]:
        cancel()
        other = int(nearest[row])
        if status[row] != PairStatus.NOT_MUTUAL:
            continue
        if status[other] == PairStatus.NEAREST_AMBIGUOUS:
            status[row] = PairStatus.PARTNER_AMBIGUOUS
            continue
        if status[other] != PairStatus.NOT_MUTUAL or nearest[other] != row:
            continue
        status[[row, other]] = PairStatus.PAIRED
        partner[row], partner[other] = other, row
    for row in groups[1]:
        cancel()
        if (
            status[row] == PairStatus.NOT_MUTUAL
            and status[nearest[row]] == PairStatus.NEAREST_AMBIGUOUS
        ):
            status[row] = PairStatus.PARTNER_AMBIGUOUS
    return partner


def pair_points(points, origins, normals, support, settings, *, chunk_rows, cancel):
    """高度跃变保留既有面内配对、模型高度和实际有符号高差要求。"""
    sides, status = classify_points(
        points,
        origins,
        normals,
        support.support.max_residual,
        chunk_rows=chunk_rows,
        cancel=cancel,
    )
    partner = mutual_pairs(
        points[:, :2],
        sides,
        status,
        settings.max_planar_gap,
        settings.tie_tolerance,
        chunk_rows=chunk_rows,
        cancel=cancel,
    )
    metrics = np.full((len(points), 3), np.nan, dtype="<f8")
    for row in np.flatnonzero((sides == 0) & (partner >= 0)):
        cancel()
        other = int(partner[row])
        delta = points[other] - points[row]
        midpoint = points[row, :2] + delta[:2] / 2
        heights = [
            origins[s, 2] - (midpoint - origins[s, :2]) @ normals[s, :2] / normals[s, 2]
            for s in range(2)
        ]
        jump = heights[1] - heights[0]
        if not np.isfinite(jump):
            raise InvalidRequestError("实测配对高度模型超出数值范围")
        if (
            abs(jump) < support.candidate_delta
            or abs(delta[2]) < support.candidate_delta
            or np.sign(jump) != np.sign(delta[2])
        ):
            status[[row, other]] = PairStatus.NOT_HEIGHT_JUMP
            partner[[row, other]] = -1
            continue
        status[[row, other]] = PairStatus.PAIRED
        partner[row], partner[other] = other, row
        gap = float(np.hypot(*delta[:2]))
        distance = float(np.hypot(gap, delta[2]))
        metrics[row] = gap, distance, delta[2]
        metrics[other] = gap, distance, -delta[2]
    cancel()
    return sides, status, partner, metrics


def pair_normal_points(
    points, origins, normals, support, settings, *, chunk_rows, cancel
):
    """法向边使用三维间距，不虚构高度评价面或有符号高差。"""
    sides, status = classify_points(
        points,
        origins,
        normals,
        support.support.max_residual,
        chunk_rows=chunk_rows,
        cancel=cancel,
    )
    partner = mutual_pairs(
        points,
        sides,
        status,
        support.max_pair_distance,
        settings.tie_tolerance,
        chunk_rows=chunk_rows,
        cancel=cancel,
    )
    metrics = np.full((len(points), 3), np.nan, dtype="<f8")
    for start in range(0, len(points), chunk_rows):
        cancel()
        rows = np.flatnonzero(partner[start : start + chunk_rows] >= 0) + start
        metrics[rows, 1] = np.linalg.norm(points[partner[rows]] - points[rows], axis=1)
    return sides, status, partner, metrics
