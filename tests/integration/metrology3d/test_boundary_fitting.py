"""独立解析直线/圆真值；不将拟合器输出作为自己的期望。"""

from math import pi

import numpy as np
import pytest

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.boundary_fitting import (
    evaluate_fit_quality,
    fit_boundary_circle,
    fit_boundary_line,
)
from tests.test_metrology3d_boundary_contracts import (
    circle_parameters,
    evaluation,
    line_parameters,
    topology,
)


def fit_line(points, parameters=None, layout=None, **changes):
    """测试显式工作容量。"""
    options = dict(max_working_bytes=10_000_000, cancel=lambda: None)
    options.update(changes)
    return fit_boundary_line(
        np.asarray(points, dtype=float),
        layout or topology(len(points), segment_id="side"),
        parameters or line_parameters(),
        **options,
    )


def fit_circle(points, parameters=None, layout=None, **changes):
    """测试显式工作容量。"""
    options = dict(max_working_bytes=10_000_000, cancel=lambda: None)
    options.update(changes)
    return fit_boundary_circle(
        np.asarray(points, dtype=float),
        layout or topology(len(points)),
        parameters or circle_parameters(),
        **options,
    )


@pytest.mark.parametrize("direction", [[1, 0, 0], [0, 1, 0], [0.6, 0.8, 0]])
@pytest.mark.parametrize("offset", [0, 1e8])
def test_tls_line_independent_truth_and_direction_flip(direction, offset):
    """水平/竖直/斜线及大平移不改物理几何。"""
    direction = np.asarray(direction)
    center = np.array([offset + 2, offset + 7, 0])
    points = center + np.arange(-5, 6)[:, None] * direction
    for sign in (1, -1):
        result = fit_line(
            points, line_parameters(positive_direction=tuple(direction * sign))
        )
        assert result.reason is None
        np.testing.assert_allclose(result.geometry["origin"], center, atol=2e-8, rtol=0)
        np.testing.assert_allclose(
            result.geometry["direction"], direction * sign, atol=2e-9, rtol=0
        )
        assert result.metrics["rms"] < 2e-8
        assert result.metrics["span"] == pytest.approx(10, abs=2e-8)


def test_tls_orthogonal_residual_and_real_segment_gap():
    """成对对称偏差给出独立 RMS；分段支持不会成为一整段。"""
    points = [[x, y, 0] for x in (-3, -2, 2, 3) for y in (-0.125, 0.125)]
    result = fit_line(points)
    assert result.metrics["rms"] == pytest.approx(0.125)
    layout = BoundaryTopology(
        point_count=6,
        segments=[
            dict(
                segment_id=name,
                start=i * 3,
                count=3,
                closed=False,
                role="open",
                orientation="open",
            )
            for i, name in enumerate(("a", "b"))
        ],
    )
    result = fit_line(
        [[x, 0, 0] for x in (-4, -3, -2, 2, 3, 4)],
        line_parameters(selection=dict(feature_id="boundary", segment_ids=["a", "b"])),
        layout,
    )
    assert len(result.intervals) == 2 and result.metrics["max_gap"] == 4
    assert [(v["start"], v["end"]) for v in result.intervals] == [(-4, -2), (2, 4)]


def test_degenerate_line_and_out_of_plane_evidence():
    """重合支持无几何，面外残差与小面内误差区分。"""
    assert fit_line([[1, 1, 1]] * 4).reason == "coincident_support"
    result = fit_line([[0, 0, 2], [1, 0, 2], [2, 0, 2]])
    assert result.metrics["plane_max_residual"] == 2 and result.metrics["rms"] == 0
    assert not evaluate_fit_quality(
        result, line_parameters(), observation_id="truth"
    ).usable
    assert fit_line([[0, 0, 0], [0, 1, 0]]).reason == "line_direction_ambiguous"


@pytest.mark.parametrize("span", [2 * pi, pi, 0.1])
@pytest.mark.parametrize("offset", [0, 1e7])
def test_geometric_circle_and_actual_arc_support(span, offset):
    """整圆/半圆/短弧均有独立真值；短弧病态由指标保留。"""
    closed = span == 2 * pi
    angles = np.linspace(0.2, 0.2 + span, 100, endpoint=not closed)
    center = np.array([offset + 2, offset - 3, 0])
    points = center + 4 * np.column_stack(
        (np.cos(angles), np.sin(angles), np.zeros(len(angles)))
    )
    result = fit_circle(points, layout=topology(len(points), closed=closed))
    assert result.reason is None, result
    np.testing.assert_allclose(result.geometry["center"], center, atol=1e-5, rtol=0)
    assert result.geometry["radius"] == pytest.approx(4, abs=1e-5)
    assert result.metrics["angular_coverage"] == pytest.approx(span, abs=1e-6)
    assert result.metrics["max_gap"] == pytest.approx(2 * pi - span, abs=1e-6)
    if span < 0.2:
        assert result.metrics["jacobian_ratio"] < 0.01
        assert not evaluate_fit_quality(
            result, circle_parameters(), observation_id="truth"
        ).usable
    else:
        assert evaluate_fit_quality(
            result, circle_parameters(), observation_id="truth"
        ).usable


def test_circle_in_rotated_evaluation_plane():
    """竖直评价面不依赖源 XY；面内二维求解仍返回三维几何。"""
    plane = evaluation(origin=[5, 6, 7], rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]])
    angles = np.linspace(0, 2 * pi, 60, endpoint=False)
    local = np.column_stack(
        (2 * np.cos(angles) + 1, 2 * np.sin(angles) - 1, np.zeros(len(angles)))
    )
    points = np.array(plane.origin) + local @ np.array(plane.rotation).T
    result = fit_circle(
        points, circle_parameters(evaluation=plane), topology(len(points), closed=True)
    )
    np.testing.assert_allclose(result.geometry["center"], [5, 7, 6], atol=1e-12)
    np.testing.assert_allclose(result.geometry["normal"], [1, 0, 0], atol=1e-12)
    assert result.geometry["radius"] == pytest.approx(2)


def test_circle_preserves_two_arcs_and_does_not_close_gap():
    """真实连接只覆盖两个独立弧，不使用 min/max 角补齐缺口。"""
    angles = np.r_[np.linspace(0, pi / 2, 20), np.linspace(pi, 3 * pi / 2, 20)]
    points = np.column_stack(
        (3 * np.cos(angles), 3 * np.sin(angles), np.zeros(len(angles)))
    )
    layout = BoundaryTopology(
        point_count=40,
        segments=[
            dict(
                segment_id=name,
                start=i * 20,
                count=20,
                closed=False,
                role="open",
                orientation="open",
            )
            for i, name in enumerate(("a", "b"))
        ],
    )
    result = fit_circle(
        points,
        circle_parameters(
            selection=dict(feature_id="boundary", segment_ids=["a", "b"])
        ),
        layout,
    )
    assert result.reason is None and len(result.intervals) == 2
    assert result.metrics["angular_coverage"] == pytest.approx(pi)
    assert result.metrics["max_gap"] == pytest.approx(pi / 2)


def test_circle_degeneracy_radius_bound_nonconvergence_and_bad_order():
    """失败不退回代数圆、不更换半径范围、不按角度重排伪造连线。"""
    assert (
        fit_circle([[x, 0, 0] for x in range(5)]).reason == "degenerate_circle_support"
    )
    angles = np.linspace(0, 2 * pi, 40, endpoint=False)
    points = np.column_stack(
        (4 * np.cos(angles), 4 * np.sin(angles), np.zeros(len(angles)))
    )
    result = fit_circle(
        points,
        circle_parameters(radius_range=(0.1, 2)),
        topology(len(points), closed=True),
    )
    assert result.reason == "radius_at_bound" and result.geometry is None
    distorted = points.copy()
    distorted[:, 0] *= 1.2
    settings = circle_parameters().solver.model_dump()
    settings["max_nfev"] = 1
    assert (
        fit_circle(distorted, circle_parameters(solver=settings)).reason
        == "circle_not_converged"
    )
    reversed_part = np.r_[np.arange(20), np.arange(30, 19, -1)]
    assert fit_circle(points[reversed_part]).reason in (
        "angular_support_gap",
        "nonmonotonic_arc",
    )


def test_fit_rejects_budget_bad_selection_and_propagates_cancellation(monkeypatch):
    """执行错误与无效测量边界分开。"""
    points = [[0, 0, 0], [1, 1, 0], [2, 0, 0]]
    with pytest.raises(InvalidRequestError, match="预算"):
        fit_line(points, max_working_bytes=1)
    with pytest.raises(InvalidRequestError, match="选择"):
        fit_line(points, layout=topology(3, segment_id="wrong"))

    def cancelled():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        fit_circle(points, cancel=cancelled)

    def failed(*args, **kwargs):
        raise RuntimeError("solver failed")

    # 真实包加载会清空模块缓存，故障必须注入本测试实际调用函数的命名空间。
    monkeypatch.setitem(fit_boundary_circle.__globals__, "least_squares", failed)
    with pytest.raises(RuntimeError, match="solver failed"):
        fit_circle(points)


def test_undefined_radial_derivative_is_geometry_failure(monkeypatch):
    """迭代恰好经过支持点时不可微；显式注入该迭代状态，不依赖舍入偶然性。"""

    def visit_support(residual, seed, **kwargs):
        kwargs["jac"](np.array([0.0, 0.0, 1.0]))
        raise AssertionError("不可微状态不应继续")

    monkeypatch.setitem(fit_boundary_circle.__globals__, "least_squares", visit_support)
    result = fit_circle([[1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0], [0, 0, 0]])
    assert result.reason == "undefined_radial_derivative" and result.geometry is None


def test_quality_rejects_wrong_unit_and_unknown_metric():
    """指标单位由算法决定，不能直接相信配方把 rad 标成 mm。"""
    points = [[0, 0, 0], [1, 0, 0], [2, 0, 0]]
    result = fit_line(points)
    params = line_parameters().model_dump(mode="json")
    params["quality_policy"]["rules"][0]["unit"] = "mm"
    with pytest.raises(InvalidRequestError, match="单位"):
        evaluate_fit_quality(
            result,
            type(line_parameters()).model_validate(params),
            observation_id="truth",
        )
