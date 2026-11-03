"""角区均衡、稳健损失和逐边覆盖；复用 SciPy 求解，不重排实测拓扑。"""

from hashlib import sha256
from math import pi

import numpy as np


def angular_weights(uv, settings, anchor):
    """每个占用角区总权重相等、总权重为点数；空角区不产生观测。"""
    delta = uv - (np.asarray(settings.center) - anchor)
    if np.any(np.linalg.norm(delta, axis=1) == 0):
        return "undefined_support_angle", None, None, None
    angle = (np.arctan2(delta[:, 1], delta[:, 0]) - settings.start_angle) % (2 * pi)
    if np.any(angle > settings.sweep):
        return "angular_support_out_of_range", None, None, None
    bins = np.minimum(
        (angle / settings.sweep * settings.sector_count).astype(np.int64),
        settings.sector_count - 1,
    )
    counts = np.bincount(bins, minlength=settings.sector_count)
    occupied = np.count_nonzero(counts)
    weights = len(uv) / (occupied * counts[bins].astype(np.float64))
    return None, weights, bins, counts


def circle_weights(uv, settings, anchor, topology, *, cancel):
    """复用角域检查；连续方法只将已有边的面内弦长各半分配给两端。"""
    cancel()
    reason, weights, bins, counts = angular_weights(uv, settings, anchor)
    if reason or settings.kind == "angular-soft-l1":
        return reason, weights, bins, counts
    if settings.kind != "arc-length-soft-l1":
        raise ValueError("unknown_circle_weight_method")
    weights = np.zeros(len(uv), dtype=np.float64)
    for segment in topology.segments:
        # 分块不连接片段间缺口；闭合边只在原拓扑明确闭合时贡献。
        end = segment.start + segment.count
        for start in range(segment.start, end - 1, 65536):
            cancel()
            stop = min(start + 65536, end - 1)
            lengths = np.linalg.norm(uv[start + 1 : stop + 1] - uv[start:stop], axis=1)
            if not np.isfinite(lengths).all() or np.any(lengths <= 0):
                return "degenerate_arc_edge", None, None, None
            weights[start:stop] += lengths / 2
            weights[start + 1 : stop + 1] += lengths / 2
        if segment.closed:
            length = np.linalg.norm(uv[end - 1] - uv[segment.start])
            if not np.isfinite(length) or length <= 0:
                return "degenerate_arc_edge", None, None, None
            weights[end - 1] += length / 2
            weights[segment.start] += length / 2
    cancel()
    total = weights.sum()
    if not np.isfinite(total) or total <= 0 or np.any(weights <= 0):
        return "degenerate_arc_support", None, None, None
    weights *= len(uv) / total
    return None, weights, bins, counts


def weighted_soft_l1(weights):
    """w*rho(r²/s²)，不是 rho(w*r²/s²)，保持各角区相同物理软阈值。"""

    def loss(z):
        """SciPy callable loss 需要函数值、一阶及二阶导数。"""
        root = np.sqrt(1 + z)
        return np.vstack((2 * z / (root + 1), 1 / root, -0.5 / (root**3))) * weights

    return loss


def merge_spans(spans):
    """合并有真实相邻边贡献的角区，不按最远两端补齐中间缺口。"""
    merged = []
    for begin, end in sorted(spans):
        if end <= begin:
            continue
        if not merged or begin > merged[-1][1]:
            merged.append([begin, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def target_gap(spans, start, sweep):
    """显式目标弧域内的最大未覆盖角，包括目标两端，不与整周缺口混用。"""
    clipped = []
    for begin, end in spans:
        for offset in (-2 * pi, 0, 2 * pi):
            lo, hi = max(0.0, begin - start + offset), min(sweep, end - start + offset)
            if hi > lo:
                clipped.append((lo, hi))
    cursor, gap = 0.0, 0.0
    for begin, end in merge_spans(clipped):
        gap = max(gap, begin - cursor)
        cursor = end
    return max(gap, sweep - cursor)


def measured_arc_support(uv, center, topology, maximum_step, inliers, *, cancel):
    """回折按每条真实边的最短转角保留；外点剔除统计不能连接跨过它的边。"""
    intervals, all_spans, inlier_spans = [], [], []
    for segment in topology.segments:
        cancel()
        rows = np.arange(segment.start, segment.start + segment.count)
        if segment.closed:
            rows = np.r_[rows, rows[0]]
        delta = uv[rows] - center
        if np.any(np.linalg.norm(delta, axis=1) == 0):
            return "undefined_support_angle", (), (), ()
        angle = np.arctan2(delta[:, 1], delta[:, 0])
        steps = np.angle(np.exp(1j * np.diff(angle)))
        if np.any(abs(steps) > maximum_step):
            return "angular_support_gap", (), (), ()
        pieces = []
        for index, step in enumerate(steps):
            if index % 1024 == 0:
                cancel()
            begin = min(float(angle[index]), float(angle[index] + step)) % (2 * pi)
            end = begin + abs(float(step))
            spans = [(begin, min(2 * pi, end))]
            if end > 2 * pi:
                spans.append((0.0, end - 2 * pi))
            pieces.extend(spans)
            if inliers[rows[index]] and inliers[rows[index + 1]]:
                inlier_spans.extend(spans)
        merged = merge_spans(pieces)
        if not merged:
            return "degenerate_arc_support", (), (), ()
        all_spans.extend(merged)
        intervals.append(
            dict(
                segment_id=segment.segment_id,
                start_angle=None,
                sweep=None,
                pieces=[dict(start_angle=lo, sweep=hi - lo) for lo, hi in merged],
            )
        )
    return None, tuple(intervals), merge_spans(all_spans), merge_spans(inlier_spans)


def weighting_evidence(residuals, weights, bins, counts, settings):
    """残差阈值仅定义质量统计的实测支持；求解不删点，也不制造代表点。"""
    inliers = abs(residuals) <= settings.inlier_residual
    sector_inliers = np.bincount(bins[inliers], minlength=settings.sector_count)
    evidence = dict(
        candidate_count=len(residuals),
        inlier_count=int(inliers.sum()),
        sector_counts=counts.tolist(),
        sector_inliers=sector_inliers.tolist(),
        residuals_sha256=sha256(
            np.asarray(residuals, dtype="<f8").tobytes()
        ).hexdigest(),
        weights_sha256=sha256(np.asarray(weights, dtype="<f8").tobytes()).hexdigest(),
    )
    return inliers, evidence
