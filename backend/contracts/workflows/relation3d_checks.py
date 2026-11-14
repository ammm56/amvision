"""关系持久证据的有限代数核对；不扫描云、不拟合、不补支持。"""

from math import atan2, pi, sqrt

from backend.contracts.workflows.dimension3d_evidence import close, dot


def _sub(a, b):
    """小型三维向量差。"""
    return tuple(x - y for x, y in zip(a, b))


def _norm(a):
    """有限元数据向量长度。"""
    return sqrt(dot(a, a))


def _project(a, space):
    """评价面投影仅用于证据代数，不依赖摄像机。"""
    if space.kind == "spatial":
        return a
    return tuple(dot(a, tuple(row[i] for row in space.plane.rotation)) for i in (0, 1))


def _same(a, b):
    """比较序列化小型坐标，不按工件尺寸扩大容差。"""
    return all(close(x, y) for x, y in zip(a, b))


def _line_contact(side, point, finite):
    """确认构造点属于原模型与真实支持区间，不夹取端点。"""
    line = side.feature.geometry
    delta = _sub(point, line.origin)
    parameter = dot(delta, line.direction)
    if not _same(delta, tuple(parameter * d for d in line.direction)):
        raise ValueError("关系落点不在原直线模型上")
    if finite and not any(
        i.start <= parameter <= i.end for i in side.feature.intervals
    ):
        raise ValueError("关系落点不在真实线段支持内")


def _parallel_pairs(a, b, alpha, beta):
    """有界核对原区间的重叠，不以接触点筛掉其他可用解。"""
    if len(a.feature.intervals) * len(b.feature.intervals) > 8192:
        raise ValueError("关系支持组合超出证据上限")
    pairs, intervals = [], []
    for ia in a.feature.intervals:
        for ib in b.feature.intervals:
            low, high = sorted(((ib.start - beta) / alpha, (ib.end - beta) / alpha))
            low, high = max(low, ia.start), min(high, ia.end)
            if low <= high:
                pairs.append((ia.segment_id, ib.segment_id))
                intervals.append((low, high))
    return pairs, intervals


def check_relation_geometry(item):
    """量值必须与原模型、唯一性及有限接触证据对应。"""
    p, g = item.method.parameters, item.geometry
    method, space = p.relation, p.space
    a, b = item.support
    metrics = {m.item_id: m.value for m in item.quality.metrics.items}
    expected_unique = int(g.contacts_unique) if g.contacts_unique is not None else None
    if metrics["contacts_unique"] != expected_unique:
        raise ValueError("最近点唯一性与质量指标不一致")
    if method.kind.endswith("angle"):
        if g.endpoints is not None or g.contacts_unique is not None or g.support_pairs:
            raise ValueError("角度不得携带最近点对")
        vectors = [
            side.feature.geometry.direction
            if method.kind == "line-angle"
            else side.plane.geometry.normal
            for side in (a, b)
        ]
        vectors = [_project(v, space) for v in vectors]
        lengths = [_norm(v) for v in vectors]
        minimum = space.min_direction_norm if space.kind == "projection" else 0
        if any(n == 0 or n < minimum for n in lengths):
            raise ValueError("角度投影退化")
        u, v = [tuple(x / n for x in vector) for vector, n in zip(vectors, lengths)]
        cosine = max(-1.0, min(1.0, dot(u, v)))
        cross = (
            u[0] * v[1] - u[1] * v[0]
            if len(u) == 2
            else _norm(
                (
                    u[1] * v[2] - u[2] * v[1],
                    u[2] * v[0] - u[0] * v[2],
                    u[0] * v[1] - u[1] * v[0],
                )
            )
        )
        expected = atan2(
            abs(cross), abs(cosine) if method.angle_mode == "unoriented" else cosine
        )
        if method.angle_mode == "signed":
            expected = pi if cross == 0 and cosine < 0 else atan2(cross, cosine)
    elif g.contacts_unique is False:
        if method.kind != "line-line" or g.endpoints is not None:
            raise ValueError("非唯一接触必须来自平行线关系")
        x, y = a.feature.geometry, b.feature.geometry
        u, v = _project(x.direction, space), _project(y.direction, space)
        if not _norm(u) or not _norm(v):
            raise ValueError("平行线投影退化")
        alpha = dot(u, v) / dot(v, v)
        if _norm(
            _sub(u, tuple(alpha * q for q in v))
        ) > 32 * 2.220446049250313e-16 * _norm(u):
            raise ValueError("非平行线不能声明非唯一最近点")
        delta = _project(_sub(y.origin, x.origin), space)
        beta = -dot(delta, v) / dot(v, v)
        expected = _norm(_sub(delta, tuple(-beta * q for q in v)))
        pairs, intervals = [], []
        if method.support_mode == "finite":
            pairs, intervals = _parallel_pairs(a, b, alpha, beta)
            if (
                not pairs
                or len(set(intervals)) == 1
                and intervals[0][0] == intervals[0][1]
            ):
                raise ValueError("非唯一有限关系缺少多个真实落点")
        if tuple(pairs) != g.support_pairs:
            raise ValueError("关系支持配对与真实区间不一致")
    else:
        if g.contacts_unique is not True or g.endpoints is None:
            raise ValueError("唯一关系必须提供完整构造落点")
        x, y = g.endpoints
        finite = getattr(method, "support_mode", None) == "finite"
        delta = _project(_sub(y, x), space)
        for side, point in ((a, x), (b, y)):
            if side.point and not _same(point, side.point.point):
                raise ValueError("关系落点与点来源不一致")
            if side.feature and side.feature.kind == "line":
                _line_contact(side, point, finite)
                direction = _project(side.feature.geometry.direction, space)
                if (
                    not _norm(direction)
                    or space.kind == "projection"
                    and _norm(direction) < space.min_direction_norm
                ):
                    raise ValueError("关系直线投影退化")
                if not close(dot(delta, direction), 0):
                    raise ValueError("关系落点不是模型垂足或最近点")
        expected = _norm(delta)
        if method.kind == "point-plane":
            plane = b.plane.geometry
            signed = dot(x, plane.normal) + plane.offset
            if not _same(y, tuple(v - signed * n for v, n in zip(x, plane.normal))):
                raise ValueError("点面落点与法向垂足不一致")
            expected = signed if method.value_mode == "signed" else abs(signed)
        if method.kind != "line-line" and g.support_pairs:
            raise ValueError("非线线关系不能携带段配对")
        if method.kind == "line-line":
            u, v = (
                _project(a.feature.geometry.direction, space),
                _project(b.feature.geometry.direction, space),
            )
            alpha = dot(u, v) / dot(v, v)
            parallel = _norm(
                _sub(u, tuple(alpha * q for q in v))
            ) <= 32 * 2.220446049250313e-16 * _norm(u)
            if parallel:
                if not finite:
                    raise ValueError("无限平行线没有唯一最近点对")
                offset = _project(
                    _sub(b.feature.geometry.origin, a.feature.geometry.origin), space
                )
                pairs, intervals = _parallel_pairs(
                    a, b, alpha, -dot(offset, v) / dot(v, v)
                )
                if (
                    not intervals
                    or len(set(intervals)) != 1
                    or intervals[0][0] != intervals[0][1]
                    or tuple(pairs) != g.support_pairs
                ):
                    raise ValueError("有限平行线唯一性与实际支持不一致")
            elif g.support_pairs:
                raise ValueError("非平行线不得携带平行支持配对")
            elif (
                _norm(_sub(u, tuple(alpha * q for q in v))) / _norm(u)
                < method.min_crossing_sine
            ):
                raise ValueError("关系最近点计算不满足条件数要求")
    if not close(expected, item.value):
        raise ValueError("关系量值与保存几何不一致")
