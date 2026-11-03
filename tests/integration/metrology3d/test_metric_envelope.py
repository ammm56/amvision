"""实际距离分区的独立逐行真值、预算和栅格无关性。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.envelope3d import VisibleEnvelopeSettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.envelope_selection import (
    _graph_index_dtype,
    metric_membership,
)
from tests.test_metrology3d_envelope import settings, points, extract


def metric_settings(distance=1.01, **changes):
    """解析格中心相距一，距离显式设置，不使用生产默认参数。"""
    data = settings(**changes).model_dump()
    data["selection"] = dict(
        kind="distance-connected",
        seed_min=data["selection"]["seed_min"],
        seed_max=data["selection"]["seed_max"],
        connection_distance=distance,
    )
    return VisibleEnvelopeSettings.model_validate(data)


def membership(p, config, **changes):
    """仅用于测试内核，预算及取消沿正式接口传入。"""
    options = dict(max_working_bytes=4_000_000, cancel=lambda: None)
    options.update(changes)
    return metric_membership(p, config, **options)


def independent_membership(p, config):
    """小样本全距离矩阵及逐行洪泛，不调用待测空间索引或连通算法。"""
    s = config.selection
    foreground = p[:, 2] > 0 if config.profiles.foreground == "above" else p[:, 2] < 0
    d2 = np.square(p[:, None, :2] - p[None, :, :2]).sum(axis=2)
    edges = (d2 <= s.connection_distance**2) & foreground[:, None] & foreground[None, :]
    seed = np.flatnonzero(
        foreground & np.all((p[:, :2] >= s.seed_min) & (p[:, :2] <= s.seed_max), axis=1)
    )
    selected = np.zeros(len(p), dtype=bool)
    pending = [int(seed[0])]
    selected[pending] = True
    while pending:
        for row in np.flatnonzero(edges[pending.pop()] & ~selected):
            selected[row] = True
            pending.append(int(row))
    assert selected[seed].all()
    return selected


@pytest.mark.parametrize("direction", ["above", "below"])
def test_exact_membership_order_grid_phase_and_missing_support(direction):
    p = points().astype(float)
    p = p[p[:, 1] != 5.5]
    if direction == "below":
        p[:, 2] *= -1
    config = metric_settings(
        2.01,
        profiles=dict(foreground=direction),
        selection=dict(seed_min=[4, 6], seed_max=[5, 7]),
    )
    expected = independent_membership(p, config)
    for step, origin in ((1, [0, 0]), (0.5, [0, 0]), (1, [0.5, 0.5])):
        data = config.model_dump()
        data["grid"].update(
            step=step, origin=origin, shape=[int(10 / step), int(12 / step)]
        )
        current = VisibleEnvelopeSettings.model_validate(data)
        order = np.random.default_rng(12).permutation(len(p))
        reason, selected, _, _ = membership(p[order], current)
        assert reason is None
        np.testing.assert_array_equal(selected, expected[order])
    result = extract(p, config)
    assert result.reason is None
    assert result.profiles[0]["profile"]["breaks"] == [2]
    assert result.metrics["profile_max_gap"] == 1
    np.testing.assert_array_equal(
        p[result.lineage["cell_sources"][:, 0], 1] != 5.5, True
    )


def test_ambiguous_seed_is_not_largest_component_and_empty_is_not_fallback():
    p = np.array([[4.2, 5.2, 1], [4.3, 5.2, 1], [4.8, 5.8, 1]], dtype=float)
    assert membership(p, metric_settings(0.11))[0] == "target_ambiguous"
    assert membership(p * [1, 1, -1], metric_settings(0.11))[0] == "target_not_found"
    assert membership(np.empty((0, 3)), metric_settings())[0] == "target_not_found"


def test_mixed_cell_and_clipped_target_are_invalid():
    config = metric_settings(
        0.2, selection=dict(seed_min=[4.1, 5.1], seed_max=[4.4, 5.4])
    )
    p = np.array([[4.2, 5.2, 1], [4.3, 5.2, 1], [4.8, 5.8, 1]], dtype=float)
    assert extract(p, config).reason == "mixed_target_cell"
    assert extract(points(), metric_settings(20)).reason is None
    clipped = np.vstack([points(), [-0.1, 5.5, 1]])
    assert extract(clipped, metric_settings(20)).reason == "roi_clipped"


def test_pair_budget_before_allocation_and_cancellation(monkeypatch):
    p = np.repeat([[4.5, 5.5, 1.0]], 20, axis=0)
    with pytest.raises(InvalidRequestError, match="空间索引"):
        membership(p, metric_settings(), max_working_bytes=100)
    with pytest.raises(InvalidRequestError, match="完整邻域图"):
        membership(p, metric_settings(), max_working_bytes=len(p) * 192 + 100)
    for at in range(1, 6):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == at:
                raise InterruptedError("stop")

        with pytest.raises(InterruptedError):
            membership(p, metric_settings(), cancel=cancel)
    assert membership(p, metric_settings())[1].all()


def test_explicit_method_rejects_inactive_parameters_and_bad_distance():
    data = metric_settings().model_dump()
    for field, value in (
        ("connection_distance", 0),
        ("closing_radius_cells", 0),
        ("connectivity", 8),
    ):
        changed = {**data, "selection": {**data["selection"], field: value}}
        with pytest.raises(ValidationError):
            VisibleEnvelopeSettings.model_validate(changed)


@pytest.mark.parametrize(
    "vertices,edges,expected",
    [
        (0, 0, np.int32),
        (17, 31, np.int32),
        (2**31 - 1, 0, np.int32),
        (1, 2**31 - 1, np.int32),
        (2**31, 1, np.int64),
        (1, 2**31, np.int64),
    ],
)
def test_graph_index_width_checks_vertices_and_csr_terminal(vertices, edges, expected):
    """不分配超大数组即可验证节点、边数两种溢出边界。"""
    assert _graph_index_dtype(vertices, edges) == expected


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_metric_radius_boundary_and_duplicates_match_scalar_truth(delta):
    """半径等号及相邻浮点数、不连通孤立点和精确重复点保持原始行语义。"""
    distance = 1.0 if delta == 0 else np.nextafter(1.0, 0 if delta < 0 else np.inf)
    p = np.array([[0, 0, 1], [0, 0, 1], [distance, 0, 1], [8, 0, 1]], dtype=float)
    config = metric_settings(1.0, selection=dict(seed_min=[0, 0], seed_max=[0.1, 0.1]))
    result = membership(p, config)
    assert result[0] is None
    np.testing.assert_array_equal(result[1], independent_membership(p, config))
