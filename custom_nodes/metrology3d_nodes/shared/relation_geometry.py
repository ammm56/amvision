"""已有点/线/面的关系计算；不读取预览、不拟合、不补有限支持。"""

from dataclasses import dataclass
from math import atan2, pi

import numpy as np

from backend.contracts.workflows.boundary3d_observations import LineGeometry
from backend.contracts.workflows.geometry3d import PlaneGeometry


@dataclass(frozen=True)
class RelationGeometryResult:
    """几何计算终态；未含上游质量，不能直接当产品判定。"""

    value: float | None
    reason: str | None
    reference_point: tuple[float, float, float] | None = None
    target_point: tuple[float, float, float] | None = None
    contacts_unique: bool | None = True
    support_pairs: tuple[tuple[str, str], ...] = ()
    failed_role: str | None = None


def line_support_reason(intervals, parameter):
    """只检查实际区间，不用包围区间填补中间缺口。"""
    if not intervals:
        return "missing_support"
    if any(i.start <= parameter <= i.end for i in intervals):
        return None
    return (
        "support_gap"
        if min(i.start for i in intervals) <= parameter <= max(i.end for i in intervals)
        else "outside_support"
    )


def _point(value):
    """外部物理点必须是有限三维值。"""
    result = np.asarray(value, dtype=np.float64)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError("relation_invalid_point")
    return result


def _vector(value):
    """几何方向必须来自已校验模型，不偷偷归一化错误输入。"""
    vector = _point(value)
    if abs(float(vector @ vector) - 1) > 1e-8:
        raise ValueError("relation_invalid_direction")
    return vector


def _position(value):
    """输出脱离数组视图的有限坐标。"""
    return tuple(float(x) for x in value)


def relation_geometry(
    parameters,
    reference,
    target,
    *,
    reference_intervals=(),
    target_intervals=(),
    plane_coverage=None,
    cancel,
):
    """按显式方法计算，有限平面覆盖必须由既有实测覆盖检查提供。"""
    cancel()
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        result = _relation_geometry(
            parameters,
            reference,
            target,
            reference_intervals,
            target_intervals,
            plane_coverage,
            cancel,
        )
    cancel()
    if result.value is not None and not np.isfinite(result.value):
        raise ValueError("relation_nonfinite_result")
    return result


def _relation_geometry(p, a, b, a_intervals, b_intervals, coverage, cancel):
    """SVD 解最短点对，原模型参数保持原空间长度单位。"""
    method, projection = p.relation, p.space.kind == "projection"
    basis = (
        np.asarray(p.space.plane.rotation, dtype=float)[:, :2]
        if projection
        else np.eye(3)
    )
    minimum = p.space.min_direction_norm if projection else 0.0
    kind = method.kind
    if kind.endswith("angle"):
        expected = LineGeometry if kind == "line-angle" else PlaneGeometry
        if not isinstance(a, expected) or not isinstance(b, expected):
            raise ValueError("relation_geometry_type_mismatch")
        va = _vector(a.direction if kind == "line-angle" else a.normal) @ basis
        vb = _vector(b.direction if kind == "line-angle" else b.normal) @ basis
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na < minimum or not na:
            return RelationGeometryResult(
                None, "projection_degenerate", failed_role="reference"
            )
        if nb < minimum or not nb:
            return RelationGeometryResult(
                None, "projection_degenerate", failed_role="target"
            )
        va, vb = va / na, vb / nb
        cosine = float(np.clip(va @ vb, -1, 1))
        cross = (
            float(va[0] * vb[1] - va[1] * vb[0])
            if projection
            else float(np.linalg.norm(np.cross(va, vb)))
        )
        angle = atan2(
            abs(cross), abs(cosine) if method.angle_mode == "unoriented" else cosine
        )
        if method.angle_mode == "signed":
            # 反向共线统一为 +pi，避免正负零随浮点路径翻转。
            angle = pi if cross == 0 and cosine < 0 else atan2(cross, cosine)
        return RelationGeometryResult(float(angle), None, contacts_unique=None)
    if kind == "point-point":
        x, y = _point(a), _point(b)
        return RelationGeometryResult(
            float(np.linalg.norm((y - x) @ basis)), None, _position(x), _position(y)
        )
    if kind == "point-plane":
        if not isinstance(b, PlaneGeometry):
            raise ValueError("relation_geometry_type_mismatch")
        x, normal = _point(a), _vector(b.normal)
        signed = float(x @ normal + b.offset)
        y = x - signed * normal
        if method.support_mode == "finite":
            if coverage is None:
                raise ValueError("relation_plane_coverage_required")
            reason = coverage(_position(y))
            if reason:
                return RelationGeometryResult(None, reason, failed_role="target")
        return RelationGeometryResult(
            signed if method.value_mode == "signed" else abs(signed),
            None,
            _position(x),
            _position(y),
        )
    if not isinstance(b, LineGeometry) or (
        kind == "line-line" and not isinstance(a, LineGeometry)
    ):
        raise ValueError("relation_geometry_type_mismatch")
    origin_b, direction_b = _point(b.origin), _vector(b.direction)
    db = direction_b @ basis
    nb = np.linalg.norm(db)
    if nb < minimum or not nb:
        return RelationGeometryResult(
            None, "projection_degenerate", failed_role="target"
        )
    if kind == "point-line":
        x = _point(a)
        t = float(((x - origin_b) @ basis) @ db / (db @ db))
        if method.support_mode == "finite":
            reason = line_support_reason(b_intervals, t)
            if reason:
                return RelationGeometryResult(None, reason, failed_role="target")
        y = origin_b + t * direction_b
        return RelationGeometryResult(
            float(np.linalg.norm((y - x) @ basis)), None, _position(x), _position(y)
        )
    origin_a, direction_a = _point(a.origin), _vector(a.direction)
    da = direction_a @ basis
    na = np.linalg.norm(da)
    if na < minimum or not na:
        return RelationGeometryResult(
            None, "projection_degenerate", failed_role="reference"
        )
    ua, ub = da / na, db / nb
    sine = (
        abs(float(ua[0] * ub[1] - ua[1] * ub[0]))
        if projection
        else float(np.linalg.norm(np.cross(ua, ub)))
    )
    delta = (origin_b - origin_a) @ basis
    if sine <= 32 * np.finfo(float).eps:
        # 平行最近点构成一族；只证明支持区间存在重叠，不任取一对冒充唯一落点。
        alpha = float(da @ db / (db @ db))
        beta = float(-delta @ db / (db @ db))
        pairs = []
        contact_parameter = None
        unique = method.support_mode == "finite"
        if method.support_mode == "finite":
            for ia in a_intervals:
                for ib in b_intervals:
                    cancel()
                    low, high = sorted(
                        ((ib.start - beta) / alpha, (ib.end - beta) / alpha)
                    )
                    start, end = max(ia.start, low), min(ia.end, high)
                    if start <= end:
                        pairs.append((ia.segment_id, ib.segment_id))
                        if start != end or (
                            contact_parameter is not None and contact_parameter != start
                        ):
                            unique = False
                        contact_parameter = start
            if not pairs:
                return RelationGeometryResult(
                    None, "no_supported_closest_pair", contacts_unique=False
                )
        distance = float(np.linalg.norm(delta - (delta @ ub) * ub))
        if unique:
            x = origin_a + contact_parameter * direction_a
            y = origin_b + (alpha * contact_parameter + beta) * direction_b
            return RelationGeometryResult(
                distance, None, _position(x), _position(y), support_pairs=tuple(pairs)
            )
        return RelationGeometryResult(
            distance, None, contacts_unique=False, support_pairs=tuple(pairs)
        )
    if sine < method.min_crossing_sine:
        return RelationGeometryResult(None, "ill_conditioned_closest_pair")
    ta, tb = np.linalg.lstsq(np.column_stack((da, -db)), delta, rcond=None)[0]
    if method.support_mode == "finite":
        for role, intervals, parameter in (
            ("reference", a_intervals, ta),
            ("target", b_intervals, tb),
        ):
            reason = line_support_reason(intervals, float(parameter))
            if reason:
                return RelationGeometryResult(None, reason, failed_role=role)
    x, y = origin_a + ta * direction_a, origin_b + tb * direction_b
    return RelationGeometryResult(
        float(np.linalg.norm((y - x) @ basis)), None, _position(x), _position(y)
    )
