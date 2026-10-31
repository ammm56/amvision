"""连续实测边权重的独立几何真值，不以拟合输出替代期望。"""

from math import dist

import numpy as np
import pytest
from scipy.optimize import minimize

from backend.contracts.workflows.boundary3d import BoundaryTopology, FitCircleParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.circle_weighting import circle_weights
from custom_nodes.metrology3d_nodes.shared.boundary_fitting import evaluate_fit_quality
from tests.integration.metrology3d.test_circle_weighting import robust_parameters
from tests.integration.metrology3d.test_boundary_fitting import fit_circle


def arc_parameters(**changes):
    """仅改变显式方法，保留原几何及完整残差门禁。"""
    value = robust_parameters(**changes).model_dump(mode="json")
    value["robust"]["kind"] = "arc-length-soft-l1"
    return FitCircleParameters.model_validate(value)


def layout(counts, closed=False):
    """构造有序段，无段间隐含连接。"""
    start, segments = 0, []
    for index, count in enumerate(counts):
        segments.append(
            dict(
                segment_id=f"s{index}",
                start=start,
                count=count,
                closed=closed,
                role="outer" if closed else "open",
                orientation="ccw" if closed else "open",
            )
        )
        start += count
    return BoundaryTopology(point_count=start, segments=segments)


def independent_lengths(points, topology):
    """标量逐边真值；不调用生产权重函数。"""
    values = [0.0] * len(points)
    for segment in topology.segments:
        rows = list(range(segment.start, segment.start + segment.count))
        pairs = list(zip(rows, rows[1:]))
        if segment.closed:
            pairs.append((rows[-1], rows[0]))
        for left, right in pairs:
            half = dist(points[left], points[right]) / 2
            values[left] += half
            values[right] += half
    return np.asarray(values) * len(values) / sum(values)


@pytest.mark.parametrize("closed", [False, True])
def test_edge_weights_no_gap_and_explicit_closure(closed):
    """每个端点只接收本段真实相邻边贡献；长缺口不参与权重。"""
    points = np.array([[1, 1], [2, 1], [2, 3], [100, 100], [101, 100], [102, 102]])
    topology = layout([3, 3], closed)
    reason, weights, _, _ = circle_weights(
        points, arc_parameters().robust, np.zeros(2), topology, cancel=lambda: None
    )
    assert reason is None
    np.testing.assert_allclose(
        weights, independent_lengths(points, topology), rtol=1e-14
    )
    assert weights.sum() == pytest.approx(6)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("offset", [0.0, 1e7])
def test_nonuniform_circle_truth_and_rigid_change(reverse, offset):
    """非均匀采样、倒序、远原点与倾斜评价面保持真实半径和圆心。"""
    angles = np.r_[np.linspace(0.1, 1, 150), np.linspace(1.02, 5.9, 100)]
    if reverse:
        angles = angles[::-1]
    basis = np.array([[1, 0, 0], [0, 0.6, -0.8], [0, 0.8, 0.6]])
    origin = np.array([offset, -offset, offset])
    points = (
        np.column_stack((4 * np.cos(angles), 4 * np.sin(angles), np.zeros(len(angles))))
        @ basis.T
        + origin
    )
    settings = arc_parameters()
    raw = settings.model_dump(mode="json")
    raw["evaluation"].update(origin=origin.tolist(), rotation=basis.tolist())
    result = fit_circle(points, FitCircleParameters.model_validate(raw))
    assert result.reason is None
    np.testing.assert_allclose(result.geometry["center"], origin, atol=1e-8, rtol=0)
    assert result.geometry["radius"] == pytest.approx(4, abs=1e-8)


def test_independent_objective_all_candidates_and_segment_permutation():
    """独立标量优化、片段交换和反转；不利点仍影响完整残差及质量。"""
    angles = np.r_[np.linspace(0.1, 1.3, 100), np.linspace(2, 5.8, 80)]
    radii = 4 + 0.004 * np.sin(7 * angles)
    radii[20] += 0.3
    uv = np.column_stack((radii * np.cos(angles), radii * np.sin(angles)))
    topology = layout([100, 80])
    parameters = arc_parameters(
        selection=dict(feature_id="boundary", segment_ids=["s0", "s1"])
    )
    weights = independent_lengths(uv, topology)

    def objective(value):
        """独立标量 soft_l1 目标，物理残差尺度不乘入权重。"""
        residual = np.array([dist(p, value[:2]) - value[2] for p in uv])
        return float(
            np.sum(weights * 0.01**2 * (np.sqrt(1 + (residual / 0.01) ** 2) - 1))
        )

    truth = minimize(
        objective,
        [0, 0, 4],
        method="Nelder-Mead",
        options=dict(xatol=1e-11, fatol=1e-14, maxiter=3000),
    )
    assert truth.success
    result = fit_circle(np.c_[uv, np.zeros(len(uv))], parameters, topology)
    assert result.reason is None
    np.testing.assert_allclose(
        [*result.geometry["center"][:2], result.geometry["radius"]], truth.x, atol=1e-7
    )
    assert result.solver["weighting"]["candidate_count"] == len(uv)
    assert result.metrics["max_residual"] > 0.29
    assert not evaluate_fit_quality(result, parameters, observation_id="truth").usable
    permuted = np.r_[uv[100:][::-1], uv[:100][::-1]]
    other = fit_circle(
        np.c_[permuted, np.zeros(len(uv))], parameters, layout([80, 100])
    )
    assert other.reason is None
    np.testing.assert_allclose(
        other.geometry["center"], result.geometry["center"], atol=1e-9
    )
    assert other.geometry["radius"] == pytest.approx(
        result.geometry["radius"], abs=1e-9
    )


def test_bad_edges_budget_and_mid_weight_cancellation():
    """重复点不静默删去；超预算及取消不被包装成正常测量结果。"""
    points = np.array([[1.0, 1], [1, 1], [2, 2]])
    reason, *_ = circle_weights(
        points, arc_parameters().robust, np.zeros(2), layout([3]), cancel=lambda: None
    )
    assert reason == "degenerate_arc_edge"
    with pytest.raises(InvalidRequestError, match="预算"):
        fit_circle(np.c_[points, np.zeros(3)], arc_parameters(), max_working_bytes=100)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        circle_weights(
            points, arc_parameters().robust, np.zeros(2), layout([3]), cancel=cancel
        )
    assert calls == 2
