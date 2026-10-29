"""F3 独立格阵真值；不调用待测算法生成期望值。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.envelope3d import (
    VisibleEnvelopeSettings,
    ProfileQuantileContact,
)
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.envelope_profiles import (
    extract_envelope_profiles,
)
from custom_nodes.metrology3d_nodes.shared.envelope_statistics import profile_spans
from backend.contracts.workflows.envelope3d import RobustProfileSpans
from tests.integration.metrology3d.test_boundary_extraction import region


def settings(**changes):
    """小型整数格阵，前景四乘六格，所有参数显式。"""
    data = dict(
        grid=dict(origin=[0, 0], step=1, shape=[10, 12], min_cell_count=1),
        selection=dict(
            seed_min=[4, 5], seed_max=[5, 6], connectivity=4, closing_radius_cells=0
        ),
        profiles=dict(
            foreground="above",
            edge_policy="interpolate-or-cell-edge",
            min_observed_length=2,
        ),
    )
    for key, value in changes.items():
        data[key].update(value)
    return VisibleEnvelopeSettings.model_validate(data)


def points():
    """格中心高度正负一，真实阈值交点在整数格边。"""
    return np.asarray(
        [
            (i + 0.5, j + 0.5, 1 if 3 <= i < 7 and 3 <= j < 9 else -1)
            for i in range(10)
            for j in range(12)
        ],
        dtype=np.float32,
    )


def extract(p=None, config=None, **changes):
    """评价面 z=0，ROI 显式且大于格阵。"""
    options = dict(
        evaluation=EvaluationPlane3d(
            frame_id="fixture",
            length_unit="mm",
            origin=[0, 0, 0],
            rotation=np.eye(3).tolist(),
        ),
        region=CropCloudParameters.model_validate(region()),
        max_working_bytes=4_000_000,
        cancel=lambda: None,
    )
    options.update(changes)
    return extract_envelope_profiles(
        points() if p is None else p,
        settings=settings() if config is None else config,
        **options,
    )


def test_analytic_rectangle_positions_and_exact_cell_sources():
    """四边独立解析为 x=3/7、y=3/9，来源每格恰好一个父行。"""
    p = points()
    result = extract(p)
    assert result.reason is None
    expected = (
        [(3, y + 0.5, 0) for y in range(3, 9)]
        + [(7, y + 0.5, 0) for y in range(3, 9)]
        + [(x + 0.5, 3, 0) for x in range(3, 7)]
        + [(x + 0.5, 9, 0) for x in range(3, 7)]
    )
    np.testing.assert_allclose(result.positions, expected, rtol=0, atol=1e-12)
    lineage = result.lineage
    np.testing.assert_array_equal(
        lineage["cell_offsets"][:, 0], np.arange(len(lineage["cell_indices"]) + 1)
    )
    for cell, row in zip(lineage["cell_indices"], lineage["cell_sources"][:, 0]):
        np.testing.assert_array_equal(p[row, :2], cell + 0.5)
    assert (
        result.metrics["estimated_fraction"] == 0
        and result.metrics["profile_coverage"] == 1
    )
    assert np.array_equal(p, points())


def test_missing_low_neighbors_are_explicit_estimates_not_fake_interpolation():
    """只有顶面时仍是可见包络；每个边点明确记缺少邻居。"""
    p = points()
    result = extract(p[p[:, 2] > 0])
    assert result.reason is None and result.metrics["estimated_fraction"] == 1
    assert result.metrics["missing_neighbor_fraction"] == 1
    np.testing.assert_array_equal(result.lineage["profile_kinds"], 2)
    np.testing.assert_array_equal(result.lineage["profile_weights"][:, 0], 1)


def test_closed_grouping_does_not_fill_missing_observations_or_hide_clipped_roi():
    """闭运算桥接只用于归属，缺失站位仍断开；ROI 截断不因形态学消失。"""
    p = points()
    p = p[p[:, 1] != 5.5]
    result = extract(p, settings(selection=dict(closing_radius_cells=1)))
    assert result.reason is None and result.profiles[0]["profile"]["breaks"] == [2]
    assert result.metrics["profile_coverage"] == pytest.approx(5 / 6)
    assert result.metrics["profile_max_gap"] == 1
    assert result.metrics["profile_max_jump"] == 2
    clipped = points()
    clipped[(clipped[:, 0] < 7) & (clipped[:, 1] > 3) & (clipped[:, 1] < 9), 2] = 1
    assert (
        extract(clipped, settings(selection=dict(closing_radius_cells=1))).reason
        == "roi_clipped"
    )


def test_seed_multiple_components_rejects_instead_of_selecting_largest():
    """种子覆盖两个分离前景，不按面积选一个。"""
    p = points()
    p[:, 2] = -1
    p[
        ((p[:, 0] < 3) | (p[:, 0] > 7))
        & (p[:, 0] > 1)
        & (p[:, 0] < 9)
        & (p[:, 1] > 3)
        & (p[:, 1] < 9),
        2,
    ] = 1
    assert (
        extract(p, settings(selection=dict(seed_min=[1, 4], seed_max=[9, 8]))).reason
        == "target_ambiguous"
    )


def test_contour_step_is_not_a_missing_station():
    """相邻实测站位处的内凹轮廓要断线，但不能声称中间缺了观测站。"""
    p = points()
    p[(p[:, 0] < 5) & (p[:, 1] > 5) & (p[:, 1] < 8), 2] = -1
    result = extract(p, settings(selection=dict(seed_min=[5, 4], seed_max=[6, 5])))
    assert result.reason is None
    assert result.metrics["profile_coverage"] == 1
    assert result.metrics["profile_max_gap"] == 0
    assert result.metrics["profile_max_jump"] > 2
    assert result.profiles[0]["profile"]["breaks"] == [2, 5]


def test_tilt_translation_and_point_order_preserve_same_evaluation_measurement():
    """旋转点云与评价系的解析真值不依赖点顺序。"""
    angle = 0.4
    r = np.array(
        [
            [np.cos(angle), 0, np.sin(angle)],
            [0, 1, 0],
            [-np.sin(angle), 0, np.cos(angle)],
        ]
    )
    offset = np.array([4.0, -5.0, 2.0])
    p = points().astype(float) @ r.T + offset
    expected = extract().positions @ r.T + offset
    e = EvaluationPlane3d(
        frame_id="fixture",
        length_unit="mm",
        origin=offset.tolist(),
        rotation=r.tolist(),
    )
    actual = extract(p[np.random.default_rng(12).permutation(len(p))], evaluation=e)
    assert actual.reason is None
    np.testing.assert_allclose(actual.positions, expected, rtol=0, atol=1e-12)


def test_bad_data_budget_and_cancel_never_produce_partial_result():
    """输入错误不是几何无效，取消传播到既有资源边界。"""
    bad = points()
    bad[0, 0] = np.nan
    with pytest.raises(InvalidRequestError, match="无效点"):
        extract(bad)
    with pytest.raises(InvalidRequestError, match="预算"):
        extract(max_working_bytes=100)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 5:
            raise InterruptedError("stop")

    with pytest.raises(InterruptedError, match="stop"):
        extract(cancel=cancel)


def test_settings_reject_unrepresentable_grid_and_outside_seed():
    """不能悄悄改变网格原点或夹住错误种子。"""
    with pytest.raises(ValidationError):
        settings(grid=dict(origin=[1e20, 1e20], step=1))
    with pytest.raises(ValidationError):
        settings(selection=dict(seed_min=[-1, 0]))


def test_statistical_endpoint_requires_true_linear_rank_and_coefficient():
    """分位端点保存真实统计来源而非伪造极值顶点。"""
    data = dict(
        kind="profile-quantile",
        side="u-min",
        sample_count=6,
        quantile=0.02,
        method="linear",
        ranks=[0, 1],
        vertex_indices=[3, 1],
        weight=0.1,
    )
    ProfileQuantileContact.model_validate(data)
    with pytest.raises(ValidationError):
        ProfileQuantileContact.model_validate({**data, "weight": 0.2})


def test_profile_quantiles_are_independent_per_side_and_do_not_use_extrema():
    """六个左侧站位为 0..5，2% 分位解析值为 0.1，而不是极值零。"""
    result = extract()
    values = result.positions.copy()
    values[:6, 0] = np.arange(6)
    e = EvaluationPlane3d(
        frame_id="fixture",
        length_unit="mm",
        origin=[0, 0, 0],
        rotation=np.eye(3).tolist(),
    )
    mode = RobustProfileSpans(
        kind="robust-profile-spans",
        lower_quantile=0.02,
        upper_quantile=0.98,
        quantile_method="linear",
    )
    output = profile_spans(
        values,
        result.profiles,
        e,
        mode,
        max_working_bytes=1_000_000,
        cancel=lambda: None,
    )
    assert output["span_u"] == pytest.approx(6.9) and output["span_v"] == pytest.approx(
        6
    )
    assert output["contacts"][0].ranks == (0, 1)
    assert output["contacts"][0].weight == pytest.approx(0.1)
