"""已有圆上的量值；复用实测逐边角区分析，不调用拟圆求解器。"""

from dataclasses import dataclass
from math import fsum, pi

import numpy as np

from backend.contracts.workflows.boundary3d import BoundaryTopology
from custom_nodes.metrology3d_nodes.shared.boundary_fitting import circle_intervals
from custom_nodes.metrology3d_nodes.shared.circle_weighting import measured_arc_support


@dataclass(frozen=True)
class ArcAnalysis:
    """失败不输出几何；调用方仍保留原圆及完整支持身份。"""

    reason: str | None
    geometry: dict | None


def analyze_arc(
    positions,
    topology,
    circle,
    evaluation,
    selection,
    mode,
    *,
    maximum_step,
    max_working_bytes,
    cancel,
):
    """选择只限制量值支持，不能改变上游拟圆模型或质量。

    positions 与 topology 始终对应完整 CircleFeature.support。
    内核在局部转为 float64，不修改保存和传递精度。
    """
    cancel()
    if len(positions) != topology.point_count:
        raise ValueError("arc_support_size_mismatch")
    if len(positions) * 1024 > max_working_bytes:
        raise ValueError("arc_working_budget_exceeded")
    selected = selection.resolve(topology)
    segments = tuple(s for s in topology.segments if s.segment_id in selected)
    # resolve 的顺序必须与证据一致；不依据屏幕位置重新排序。
    by_id = {s.segment_id: s for s in segments}
    segments = tuple(by_id[key] for key in selected)
    continuous = mode.kind == "continuous-arc"
    if continuous and (len(segments) != 1 or segments[0].closed):
        return ArcAnalysis("requires_single_open_segment", None)
    basis = np.asarray(evaluation.rotation, dtype=float)
    normal = basis[:, 2]
    if not np.allclose(normal, circle.normal, atol=1e-8, rtol=0):
        raise ValueError("arc_circle_evaluation_mismatch")
    points = np.asarray(positions, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("arc_invalid_positions")
    center = np.asarray(circle.center)
    uv = (points - center) @ basis[:, :2]
    selected_topology = BoundaryTopology.model_construct(
        point_count=topology.point_count, segments=segments
    )
    reason, intervals, union, _ = measured_arc_support(
        uv,
        np.zeros(2),
        selected_topology,
        maximum_step,
        np.ones(len(points), dtype=bool),
        cancel=cancel,
    )
    if reason:
        return ArcAnalysis(reason, None)
    parts = []
    for segment, interval in zip(segments, intervals):
        cancel()
        part = points[segment.start : segment.start + segment.count]
        lengths = np.linalg.norm(np.diff(part, axis=0), axis=1)
        if np.any(lengths <= 0):
            return ArcAnalysis("degenerate_arc_edge", None)
        polyline = float(lengths.sum())
        if segment.closed:
            closing = float(np.linalg.norm(part[-1] - part[0]))
            if closing <= 0:
                return ArcAnalysis("degenerate_arc_edge", None)
            polyline += closing
        one = BoundaryTopology.model_construct(
            point_count=topology.point_count, segments=(segment,)
        )
        monotonic_reason, signed, _, _ = circle_intervals(
            uv, np.zeros(2), one, maximum_step, cancel=cancel
        )
        if continuous and monotonic_reason:
            return ArcAnalysis(monotonic_reason, None)
        sweep = None if monotonic_reason else signed[0]["sweep"]
        if continuous and abs(sweep) >= 2 * pi:
            return ArcAnalysis("requires_open_sweep", None)
        pieces = interval["pieces"]
        parts.append(
            dict(
                segment_id=segment.segment_id,
                closed=segment.closed,
                point_count=segment.count,
                pieces=pieces,
                signed_sweep=sweep,
                angular_reason=monotonic_reason,
                polyline_length=polyline,
            )
        )
    coverage = fsum(hi - lo for lo, hi in union)
    sum_coverage = fsum(p["sweep"] for part in parts for p in part["pieces"])
    geometry = dict(
        circle=circle,
        parts=parts,
        pieces=[dict(start_angle=lo, sweep=hi - lo) for lo, hi in union],
        coverage_angle=coverage,
        overlap_angle=max(0.0, sum_coverage - coverage),
        polyline_length=fsum(part["polyline_length"] for part in parts),
        start=None,
        end=None,
        signed_sweep=None,
        direction=None,
    )
    if continuous:
        segment = segments[0]
        indices = [segment.start, segment.start + segment.count - 1]
        sweep = parts[0]["signed_sweep"]
        if mode.traversal == "reverse-source-order":
            indices.reverse()
            sweep = -sweep
        endpoints = []
        for index in indices:
            cancel()
            radial = basis[:, :2] @ uv[index]
            projected = center + circle.radius * radial / np.linalg.norm(radial)
            endpoints.append(
                dict(
                    vertex_index=index,
                    point=points[index],
                    projected=projected,
                )
            )
        geometry.update(
            start=endpoints[0],
            end=endpoints[1],
            signed_sweep=sweep,
            direction="ccw" if sweep > 0 else "cw",
        )
    cancel()
    return ArcAnalysis(None, geometry)
