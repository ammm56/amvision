"""有序边界的面内直线/圆内核；使用 NumPy/SciPy，不包含节点或资源注册。"""

from dataclasses import dataclass
from math import pi

import numpy as np
from scipy.optimize import least_squares
from backend.contracts.workflows.boundary3d_quality import boundary_metric_units

from backend.contracts.workflows.boundary3d import (
    BoundaryTopology,
    FitCircleParameters,
    FitLineParameters,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.geometry_quality import geometry_quality


@dataclass(frozen=True)
class BoundaryFit:
    """几何候选及原始质量；handler 必须再执行现有几何质量规则。"""

    reason: str | None
    geometry: dict | None
    metrics: dict[str, float | int | None]
    intervals: tuple[dict, ...]
    solver: dict | None = None


class _UndefinedRadialDerivative(Exception):
    """合法支持在迭代圆心处不可微，不将这种几何退化当配置错误。"""


def fit_metric_units(parameters):
    """成功及缺测共用同一指标集合和物理单位。"""
    if not isinstance(parameters, (FitLineParameters, FitCircleParameters)):
        raise InvalidRequestError("边界拟合质量需要已校验参数")
    return boundary_metric_units(
        "line" if isinstance(parameters, FitLineParameters) else "circle",
        parameters.evaluation.length_unit,
    )


def evaluate_fit_quality(result, parameters, *, observation_id):
    """同一限值实现评价内核候选；候选求解成功不等于几何可用。"""
    units = fit_metric_units(parameters)
    if set(result.metrics) != set(units):
        raise InvalidRequestError("边界拟合质量指标集合不一致")
    if any(
        rule.item_id not in units or rule.unit != units[rule.item_id]
        for rule in parameters.quality_policy.rules
    ):
        raise InvalidRequestError("边界拟合质量使用未知指标或错误单位")
    return geometry_quality(
        observation_id,
        {name: (value, units[name]) for name, value in result.metrics.items()},
        parameters.quality_policy,
        reason=result.reason or "metric_unavailable",
    )


def _prepare(positions, topology, parameters, max_working_bytes, cancel):
    """核验完整已选支持并局部中心化；显示采样不能进入此入口。"""
    cancel()
    points = np.asarray(positions)
    if not isinstance(topology, BoundaryTopology) or (
        points.shape != (topology.point_count, 3)
        or points.dtype.kind != "f"
        or type(max_working_bytes) is not int
        or max_working_bytes <= 0
    ):
        raise InvalidRequestError("边界拟合形状、拓扑或预算不合法")
    # 输入工作副本、投影、SVD/Jacobian 和优化器数组；不是原生 RSS 硬上限。
    if len(points) * 1024 > max_working_bytes:
        raise InvalidRequestError("边界拟合超过显式工作预算")
    if not np.isfinite(points).all():
        raise InvalidRequestError("边界拟合支持包含无效坐标")
    actual = tuple(segment.segment_id for segment in topology.segments)
    if actual != parameters.selection.segment_ids:
        raise InvalidRequestError("边界拟合支持与明确选择的段不一致")
    with np.errstate(over="raise", invalid="raise"):
        rotation = np.asarray(parameters.evaluation.rotation)
        local = (points.astype(np.float64) - parameters.evaluation.origin) @ rotation
        anchor = local[0, :2].copy() if len(points) else np.zeros(2)
        uv = local[:, :2] - anchor
    return local, uv, anchor, rotation


def _plane_residual(local):
    """面外残差单独保留，不被径向/面内残差吞掉。"""
    return float(np.max(np.abs(local[:, 2]))) if len(local) else None


def fit_boundary_line(positions, topology, parameters, *, max_working_bytes, cancel):
    """完整支持 TLS；每个真实段分别保留参数区间，不跨缺口合并。"""
    if not isinstance(parameters, FitLineParameters):
        raise InvalidRequestError("直线拟合需要已校验参数")
    local, uv, anchor, rotation = _prepare(
        positions, topology, parameters, max_working_bytes, cancel
    )
    metrics = dict(
        support_count=len(uv),
        plane_max_residual=_plane_residual(local),
        span=None,
        direction_gap=None,
        rms=None,
        max_residual=None,
        max_gap=None,
    )
    if len(uv) < 2:
        return BoundaryFit("insufficient_support", None, metrics, ())
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        center = uv.mean(axis=0)
        centered = uv - center
        _, singular, right = np.linalg.svd(centered, full_matrices=False)
        if singular[0] == 0:
            return BoundaryFit("coincident_support", None, metrics, ())
        direction = right[0]
        global_direction = rotation[:, :2] @ direction
        alignment = float(global_direction @ parameters.positive_direction)
        metrics["direction_gap"] = float((singular[0] - singular[1]) / singular[0])
        if abs(alignment) < parameters.min_orientation_cosine:
            return BoundaryFit("line_direction_ambiguous", None, metrics, ())
        if alignment < 0:
            direction, global_direction = -direction, -global_direction
        distance = centered @ np.array([-direction[1], direction[0]])
        parameter = centered @ direction
        intervals = tuple(
            dict(
                segment_id=segment.segment_id,
                start=float(
                    parameter[segment.start : segment.start + segment.count].min()
                ),
                end=float(
                    parameter[segment.start : segment.start + segment.count].max()
                ),
            )
            for segment in topology.segments
        )
        ranges = sorted((item["start"], item["end"]) for item in intervals)
        end, gap = ranges[0][1], 0.0
        for begin, finish in ranges[1:]:
            gap = max(gap, begin - end)
            end = max(end, finish)
        metrics.update(
            span=float(np.ptp(parameter)),
            rms=float(np.sqrt(np.mean(distance**2))),
            max_residual=float(np.max(np.abs(distance))),
            max_gap=gap,
        )
        origin = np.asarray(parameters.evaluation.origin) + rotation[:, :2] @ (
            anchor + center
        )
    cancel()
    return BoundaryFit(
        None,
        dict(origin=origin.tolist(), direction=global_direction.tolist()),
        metrics,
        intervals,
    )


def _circle_intervals(uv, center, topology, maximum_step):
    """按真实相邻边展开角度；长跳变、回折或重复绕圈不能假装连续支持。"""
    pieces, intervals = [], []
    for segment in topology.segments:
        part = uv[segment.start : segment.start + segment.count] - center
        angles = np.arctan2(part[:, 1], part[:, 0])
        if segment.closed:
            angles = np.r_[angles, angles[0]]
        delta = np.angle(np.exp(1j * np.diff(angles)))
        if np.any(np.abs(delta) > maximum_step):
            return "angular_support_gap", (), None, None
        # 浮点判别只用于零转角；测量质量门槛仍由配方提供。
        nonzero = delta[np.abs(delta) > np.finfo(float).eps * 32]
        if not len(nonzero) or (nonzero.min() < 0 < nonzero.max()):
            return "nonmonotonic_arc", (), None, None
        sweep = float(delta.sum())
        if abs(sweep) > 2 * pi + np.finfo(float).eps * len(delta) * 32:
            return "overlapping_arc", (), None, None
        begin, end = sorted((float(angles[0]), float(angles[0]) + sweep))
        span = min(2 * pi, end - begin)
        if (
            segment.closed
            and abs(span - 2 * pi) > np.finfo(float).eps * len(delta) * 32
        ):
            return "incomplete_closed_arc", (), None, None
        start = begin % (2 * pi)
        intervals.append(
            dict(
                segment_id=segment.segment_id, start_angle=float(angles[0]), sweep=sweep
            )
        )
        finish = start + span
        if finish <= 2 * pi:
            pieces.append((start, finish))
        else:
            pieces.extend(((start, 2 * pi), (0, finish - 2 * pi)))
    merged = []
    for begin, finish in sorted(pieces):
        if not merged or begin > merged[-1][1]:
            merged.append([begin, finish])
        else:
            merged[-1][1] = max(merged[-1][1], finish)
    coverage = sum(end - start for start, end in merged)
    gaps = [merged[i + 1][0] - merged[i][1] for i in range(len(merged) - 1)]
    gaps.append(2 * pi - merged[-1][1] + merged[0][0])
    return None, tuple(intervals), coverage, max(gaps)


def fit_boundary_circle(positions, topology, parameters, *, max_working_bytes, cancel):
    """代数初始化后解几何径向最小二乘，半径边界/收敛/质量各自报告。"""
    if not isinstance(parameters, FitCircleParameters):
        raise InvalidRequestError("圆拟合需要已校验参数")
    local, uv, anchor, rotation = _prepare(
        positions, topology, parameters, max_working_bytes, cancel
    )
    metrics = dict(
        support_count=len(uv),
        plane_max_residual=_plane_residual(local),
        rms=None,
        max_residual=None,
        jacobian_ratio=None,
        angular_coverage=None,
        max_gap=None,
    )
    if len(uv) < 3:
        return BoundaryFit("insufficient_support", None, metrics, ())
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        offset = uv.mean(axis=0)
        centered = uv - offset
        matrix = np.column_stack((2 * centered, np.ones(len(uv))))
        initial, _, rank, _ = np.linalg.lstsq(
            matrix, np.sum(centered**2, axis=1), rcond=None
        )
        if rank < 3:
            return BoundaryFit("degenerate_circle_support", None, metrics, ())
        radius = np.sqrt(initial[2] + initial[:2] @ initial[:2])
        if radius <= 0 or not np.isfinite(radius):
            return BoundaryFit("degenerate_circle_support", None, metrics, ())
        lower, upper = parameters.radius_range
        seed = np.r_[initial[:2], np.clip(radius, lower, upper)]

        def residual(value):
            """原生迭代的每次评估均检查取消；不转成正常缺测。"""
            cancel()
            return np.linalg.norm(centered - value[:2], axis=1) - value[2]

        def jacobian(value):
            """解析径向 Jacobian；支持点恰好位于圆心时不可微。"""
            cancel()
            delta = value[:2] - centered
            norms = np.linalg.norm(delta, axis=1)
            if np.any(norms == 0):
                raise _UndefinedRadialDerivative
            return np.column_stack((delta / norms[:, None], -np.ones(len(uv))))

        try:
            result = least_squares(
                residual,
                seed,
                jac=jacobian,
                bounds=([-np.inf, -np.inf, lower], [np.inf, np.inf, upper]),
                method="trf",
                tr_solver="exact",
                loss="linear",
                f_scale=1.0,
                ftol=parameters.solver.ftol,
                xtol=parameters.solver.xtol,
                gtol=parameters.solver.gtol,
                max_nfev=parameters.solver.max_nfev,
                x_scale=parameters.solver.x_scale,
            )
        except _UndefinedRadialDerivative:
            return BoundaryFit("undefined_radial_derivative", None, metrics, ())
        cancel()
        details = dict(
            status=int(result.status),
            nfev=int(result.nfev),
            cost=float(result.cost),
            optimality=float(result.optimality),
            radius_at_bound=bool(result.active_mask[2]),
        )
        metrics.update(
            rms=float(np.sqrt(np.mean(result.fun**2))),
            max_residual=float(np.max(np.abs(result.fun))),
        )
        singular = np.linalg.svd(result.jac, compute_uv=False)
        metrics["jacobian_ratio"] = (
            float(singular[-1] / singular[0]) if singular[0] else 0.0
        )
        if not result.success:
            return BoundaryFit("circle_not_converged", None, metrics, (), details)
        if result.active_mask[2]:
            return BoundaryFit("radius_at_bound", None, metrics, (), details)
        center = result.x[:2] + offset
        reason, intervals, coverage, gap = _circle_intervals(
            uv, center, topology, parameters.max_arc_step
        )
        metrics.update(angular_coverage=coverage, max_gap=gap)
        if reason:
            return BoundaryFit(reason, None, metrics, (), details)
        origin = np.asarray(parameters.evaluation.origin) + rotation[:, :2] @ (
            anchor + center
        )
    return BoundaryFit(
        None,
        dict(
            center=origin.tolist(),
            normal=rotation[:, 2].tolist(),
            radius=float(result.x[2]),
        ),
        metrics,
        intervals,
        details,
    )
