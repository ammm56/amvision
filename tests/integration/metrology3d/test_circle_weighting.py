"""角区稳健拟圆的独立目标函数、真实拓扑、质量及拒绝路径。"""

from math import pi

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.optimize import minimize

from backend.contracts.workflows.boundary3d import BoundaryTopology, FitCircleParameters
from custom_nodes.metrology3d_nodes.shared.boundary_fitting import evaluate_fit_quality
from custom_nodes.metrology3d_nodes.shared.circle_weighting import (
    weighted_soft_l1,
    target_gap,
)
from tests.test_metrology3d_boundary_contracts import circle_parameters
from tests.integration.metrology3d.test_boundary_fitting import fit_circle


def robust_parameters(**changes):
    """仅用于独立真值测试的明确限制，不进入生产默认。"""
    value = circle_parameters().model_dump(mode="json")
    value["robust"] = dict(
        kind="angular-soft-l1",
        center=[0, 0],
        start_angle=0,
        sweep=2 * pi,
        sector_count=16,
        loss_scale=0.01,
        inlier_residual=0.05,
    )
    value["quality_policy"]["rules"] += [
        dict(item_id="inlier_fraction", unit="1", lower=0.8),
        dict(item_id="sector_coverage", unit="1", lower=0.4),
        dict(item_id="inlier_angular_coverage", unit="rad", lower=1),
        dict(item_id="inlier_jacobian_ratio", unit="1", lower=0.01),
        dict(item_id="target_max_gap", unit="rad", upper=5.3),
        dict(item_id="inlier_max_gap", unit="rad", upper=5.3),
        dict(item_id="weighted_rms", unit="mm", upper=0.01),
    ]
    value.update(changes)
    return FitCircleParameters.model_validate(value)


def test_loss_weight_is_outside_soft_l1():
    """独立有限差分核对 rho 与两阶导数，避免点密度改变物理阈值。"""
    weights = np.array([0.2, 1.0, 8.0])
    z = np.array([0.1, 1.0, 25.0])
    actual = weighted_soft_l1(weights)(z)
    h = 1e-4

    def scalar(x):
        """独立标量表达，不调用待测导数。"""
        return 2 * (np.sqrt(1 + x) - 1) * weights

    np.testing.assert_allclose(actual[0], scalar(z), rtol=1e-13)
    np.testing.assert_allclose(
        actual[1], (scalar(z + h) - scalar(z - h)) / (2 * h), rtol=1e-7
    )
    np.testing.assert_allclose(
        actual[2], (scalar(z + h) - 2 * scalar(z) + scalar(z - h)) / h**2, rtol=2e-4
    )


def test_target_domain_uses_configured_center_not_fitted_center():
    """目标起止角与权重属于配方中心，实际覆盖独立属于拟合圆心。"""
    angles = np.linspace(0.2, 2.8, 150)
    p = np.column_stack((4 * np.cos(angles), 4 * np.sin(angles), np.zeros(len(angles))))
    params = robust_parameters()
    raw = params.model_dump()
    raw["robust"].update(center=[1, 0], start_angle=0, sweep=pi)
    result = fit_circle(p, FitCircleParameters.model_validate(raw))
    assert result.reason is None
    actual = np.arctan2(p[:, 1], p[:, 0] - 1)
    assert result.metrics["angular_coverage"] == pytest.approx(2.6)
    assert result.metrics["target_max_gap"] == pytest.approx(
        max(actual[0], pi - actual[-1])
    )
    assert result.metrics["inlier_max_gap"] == result.metrics["target_max_gap"]


def test_exact_nonuniform_circle_and_reversing_real_edges():
    """局部回折不虚构转角；线性严格模式仍拒绝同一输入。"""
    angles = np.r_[
        np.linspace(0.1, 2, 150), np.linspace(1.99, 1.8, 10), np.linspace(1.81, 5.9, 90)
    ]
    points = np.column_stack(
        (4 * np.cos(angles), 4 * np.sin(angles), np.zeros(len(angles)))
    )
    assert fit_circle(points).reason == "nonmonotonic_arc"
    result = fit_circle(points, robust_parameters())
    assert result.reason is None
    assert result.geometry["radius"] == pytest.approx(4, abs=1e-11)
    np.testing.assert_allclose(result.geometry["center"], [0, 0, 0], atol=1e-11)
    assert result.metrics["angular_coverage"] == pytest.approx(5.8)
    assert result.metrics["inlier_angular_coverage"] == pytest.approx(5.8)
    assert result.intervals[0]["start_angle"] is None
    assert evaluate_fit_quality(
        result, robust_parameters(), observation_id="truth"
    ).usable
    assert result.solver["weighting"]["candidate_count"] == len(points)


def test_weighted_fit_matches_independent_scalar_objective_and_keeps_outliers():
    """不复用内核权重或残差计算；孤立偏差仍留在 raw max_residual 门禁。"""
    angles = np.r_[np.linspace(0.15, 1.2, 160), np.linspace(1.25, 5.9, 90)]
    radius = 4 + 0.004 * np.sin(7 * angles)
    radius[35] += 0.3
    points = np.column_stack(
        (radius * np.cos(angles), radius * np.sin(angles), np.zeros(len(angles)))
    )
    settings = robust_parameters()
    result = fit_circle(points, settings)
    assert result.reason is None
    sectors = [min(15, int(a / (2 * pi) * 16)) for a in angles]
    counts = [sectors.count(i) for i in range(16)]
    occupied = sum(n > 0 for n in counts)
    weights = np.array([len(angles) / (occupied * counts[s]) for s in sectors])

    def objective(value):
        residuals = (
            np.sqrt((points[:, 0] - value[0]) ** 2 + (points[:, 1] - value[1]) ** 2)
            - value[2]
        )
        return float(
            np.sum(weights * 0.01**2 * (np.sqrt(1 + (residuals / 0.01) ** 2) - 1))
        )

    independent = minimize(
        objective,
        [0, 0, 4],
        method="Nelder-Mead",
        options=dict(xatol=1e-11, fatol=1e-14, maxiter=2000),
    )
    assert independent.success
    np.testing.assert_allclose(
        [*result.geometry["center"][:2], result.geometry["radius"]],
        independent.x,
        atol=1e-7,
    )
    assert result.metrics["max_residual"] > 0.29
    assert not evaluate_fit_quality(result, settings, observation_id="truth").usable
    assert result.solver["weighting"]["inlier_count"] == len(points) - 1
    assert (
        result.metrics["inlier_angular_coverage"] < result.metrics["angular_coverage"]
    )


def test_fragments_do_not_bridge_gaps_and_target_includes_missing_ends():
    """支持段之间无虚构连线；目标起止缺测也计入最大缺口。"""
    angles = np.r_[np.linspace(0.2, 1, 40), np.linspace(2, 2.8, 40)]
    points = np.column_stack((4 * np.cos(angles), 4 * np.sin(angles), np.zeros(80)))
    layout = BoundaryTopology(
        point_count=80,
        segments=[
            dict(
                segment_id=name,
                start=i * 40,
                count=40,
                closed=False,
                role="open",
                orientation="open",
            )
            for i, name in enumerate(("a", "b"))
        ],
    )
    p = robust_parameters(selection=dict(feature_id="boundary", segment_ids=["a", "b"]))
    result = fit_circle(points, p, layout)
    assert result.reason is None
    assert result.metrics["angular_coverage"] == pytest.approx(1.6)
    assert len(result.intervals) == 2
    assert target_gap([(0.2, 1), (2, 2.8)], 0, 3.2) == pytest.approx(1)
    assert target_gap([(0, 0.2), (6, 2 * pi)], 6, 1) == pytest.approx(
        1 - (2 * pi - 6 + 0.2)
    )


def test_robust_configuration_quality_and_limits():
    """不能缺省稳健支持规则，也不能把外域点偷偷丢弃。"""
    p = robust_parameters()
    value = p.model_dump(mode="json")
    value["quality_policy"]["rules"].pop()
    with pytest.raises(ValidationError):
        FitCircleParameters.model_validate(value)
    value = p.model_dump(mode="json")
    value["robust"]["sweep"] = 1
    points = [[4 * np.cos(a), 4 * np.sin(a), 0] for a in (0.2, 0.4, 2)]
    result = fit_circle(points, FitCircleParameters.model_validate(value))
    assert result.reason == "angular_support_out_of_range"

    def cancelled():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        fit_circle(points, p, cancel=cancelled)
