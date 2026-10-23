"""局部表面和真实邻接验证；几何期望独立于三角剖分结果。"""

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.boundary_surface import build_surface
from custom_nodes._metrology3d_nodes.shared.boundary_topology import order_segments


def surface(points, **changes):
    """显式测试配置，不代表生产精度或容量。"""
    options = dict(
        origin=[0, 0, 0],
        rotation=np.eye(3),
        alpha_radius=0.8,
        max_edge_length=1.5,
        max_normal_step=0.1,
        min_projected_area=0.01,
        max_working_bytes=10_000_000,
        cancel=lambda: None,
    )
    options.update(changes)
    return build_surface(np.asarray(points, dtype=float), **options)


def segments(points, edges, **changes):
    """测试只使用真实端点身份连接。"""
    options = dict(max_working_bytes=10_000_000, cancel=lambda: None)
    options.update(changes)
    return order_segments(
        np.asarray(points, dtype=float), np.asarray(edges, dtype=np.int64), **options
    )


def test_concavity_is_not_replaced_by_convex_hull():
    """保留可分辨的凹形，不声称稀疏采样能恢复不可分辨的尖角。"""
    points = np.array(
        [(x, y, 0) for x in range(4) for y in range(4) if x <= 1 or y <= 1], dtype=float
    )
    result = surface(points)
    assert result.reason is None
    assert not np.any(np.all(points[result.faces, :2].mean(axis=1) > 1.5, axis=1))
    reason, chains = segments(points, result.boundary_edges)
    assert reason is None and len(chains) == 1 and chains[0].closed
    # 此支持尺度产生 (1,2)-(2,1) 倒角；凸包会直接连 (1,3)-(3,1)。
    boundary = {tuple(points[i]) for i in chains[0].indices}
    assert {(1, 2, 0), (2, 1, 0)} <= boundary
    assert (1, 1, 0) not in boundary


def test_missing_band_produces_two_components_not_a_bridge():
    """超过显式支持边长的空带不补齐。"""
    points = np.array([(x, y, 0) for x in (0, 1, 5, 6) for y in range(3)], dtype=float)
    result = surface(points)
    assert result.reason is None
    reason, chains = segments(points, result.boundary_edges)
    assert reason is None and len(chains) == 2 and all(c.closed for c in chains)
    for chain in chains:
        assert np.ptp(points[chain.indices, 0]) == 1


def test_multiple_holes_and_shuffle_preserve_geometric_cycles():
    """孔洞不按返回次序定义业务身份，闭段末尾不重复首点。"""
    points = np.array(
        [
            (x, y, 0)
            for x in range(11)
            for y in range(7)
            if not (2 <= x <= 3 and 2 <= y <= 3) and not (7 <= x <= 8 and 2 <= y <= 3)
        ],
        dtype=float,
    )
    expected = None
    for seed in range(4):
        data = points[np.random.default_rng(seed).permutation(len(points))]
        result = surface(data)
        reason, chains = segments(data, result.boundary_edges)
        assert reason is None and len(chains) == 3 and all(c.closed for c in chains)
        actual = {frozenset(map(tuple, data[c.indices])) for c in chains}
        if expected is None:
            expected = actual
        assert actual == expected
        assert all(len(set(c.indices)) == len(c.indices) for c in chains)


@pytest.mark.parametrize(
    "points, reason",
    [
        ([], "insufficient_support"),
        ([[0, 0, 0], [1, 0, 0]], "insufficient_support"),
        ([[0, 0, 0], [1, 0, 0], [2, 0, 0]], "degenerate_projection"),
        ([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 4]], "duplicate_projection"),
        ([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0]], "duplicate_projection"),
    ],
)
def test_projection_degeneracy_is_explicit(points, reason):
    """多层/重复投影不静默去重或随机扰动。"""
    result = surface(np.asarray(points).reshape(-1, 3))
    assert result.reason == reason and not len(result.faces)


def test_surface_support_filters_are_each_effective():
    """面积、alpha、边长、法向跳变均独立参与支持检查。"""
    points = [[0, 0, 0], [1, 0, 0], [0, 1, 0.05]]
    assert surface(points).reason is None
    for change in (
        {"alpha_radius": 0.5},
        {"max_edge_length": 1},
        {"max_normal_step": 0.01},
        {"min_projected_area": 0.6},
    ):
        assert surface(points, **change).reason == "no_supported_surface"


def test_topology_preserves_open_gap_and_rejects_branch():
    """开放两段不连线，三分叉不能用任意路径假装有序轮廓。"""
    points = [[0, 0, 0], [1, 0, 0], [2, 0, 0], [4, 0, 0], [5, 0, 0]]
    reason, chains = segments(points, [[1, 2], [4, 3], [0, 1]])
    assert reason is None and [len(c.indices) for c in chains] == [3, 2]
    assert not any(c.closed for c in chains)
    assert segments(points, [[0, 1], [1, 2], [1, 3]])[0] == "branched_boundary"
    with pytest.raises(InvalidRequestError, match="重复边"):
        segments(points, [[0, 1], [1, 0]])


def test_limits_cancellation_and_qhull_failure_propagate(monkeypatch):
    """执行错误不转换成合法缺测。"""
    points = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    with pytest.raises(InvalidRequestError, match="预算"):
        surface(points, max_working_bytes=1)
    with pytest.raises(InvalidRequestError, match="预算"):
        segments(points, [[0, 1]], max_working_bytes=1)

    def cancelled():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        surface(points, cancel=cancelled)
    with pytest.raises(InterruptedError):
        segments(points, [[0, 1]], cancel=cancelled)

    def failed(*args, **kwargs):
        raise RuntimeError("Qhull failed")

    monkeypatch.setattr(
        "custom_nodes._metrology3d_nodes.shared.boundary_surface.Delaunay", failed
    )
    with pytest.raises(RuntimeError, match="Qhull failed"):
        surface(points)


def test_many_disjoint_segments_keep_all_edges_without_merging():
    """大量断段保持独立；不通过邻近连接减少候选数量。"""
    count = 2048
    points = np.column_stack(
        (np.arange(count * 2, dtype=float), np.zeros(count * 2), np.zeros(count * 2))
    )
    edges = np.arange(count * 2).reshape(count, 2)
    reason, chains = segments(points, edges)
    assert reason is None and len(chains) == count
    assert all(not chain.closed and len(chain.indices) == 2 for chain in chains)
    np.testing.assert_array_equal(
        np.concatenate([chain.indices for chain in chains]), np.arange(count * 2)
    )
