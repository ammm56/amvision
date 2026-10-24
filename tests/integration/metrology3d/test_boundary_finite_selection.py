"""有限段选择的独立真值；不改变支持阈值或补造 ROI 交点。"""

import numpy as np
import pytest

from custom_nodes._metrology3d_nodes.shared.boundary_topology import (
    OrderedSegment,
    selected_runs,
)
from tests.integration.metrology3d.test_boundary_extraction import (
    extract,
    extract_parameters,
    region,
)


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize(
    "mask",
    [
        [False] * 5,
        [True] * 5,
        [True, True, False, True, True],
        [False, True, False, True, False],
    ],
)
def test_runs_keep_only_original_edges_and_vertices(closed, mask):
    """逐一核验源索引和拓扑边，环的首尾连续只在原环上成立。"""
    source = OrderedSegment(np.arange(len(mask)), closed)
    runs = list(selected_runs(source, mask, cancel=lambda: None))
    actual = [int(i) for part in runs for i in part.indices]
    assert sorted(actual) == list(np.flatnonzero(mask))
    for part in runs:
        assert part.closed == (closed and all(mask))
        for a, b in zip(part.indices, part.indices[1:]):
            assert b == a + 1 or (closed and a == len(mask) - 1 and b == 0)
    expected = (
        0
        if not any(mask)
        else sum(bool(value) and not mask[i - 1] for i, value in enumerate(mask))
        if closed
        else sum(
            bool(value) and (i == 0 or not mask[i - 1]) for i, value in enumerate(mask)
        )
    )
    assert len(runs) == (1 if all(mask) else expected)


def target(name, center, size):
    """显式测试窗口，与候选序号无关。"""
    return dict(
        segment_id=name,
        region=region(center=center, size=size),
        closed=False,
        role="open",
    )


def test_two_disjoint_sides_of_same_closed_boundary_are_allowed():
    """不是按整个连通域占用，左右两边分别选择且原始行号不变。"""
    points = np.array([(x, y, 0) for x in range(5) for y in range(5)], dtype="f4")
    targets = [
        target(name, (x, 2, 0), (0.2, 2.2, 1))
        for name, x in [("left", 0), ("right", 4)]
    ]
    for seed in range(3):
        shuffled = points[np.random.default_rng(seed).permutation(len(points))]
        result = extract(shuffled, extract_parameters(targets=targets))
        assert result.reason is None
        assert result.topology.point_count == 6
        np.testing.assert_array_equal(result.positions, shuffled[result.source_rows])
        for part, x in zip(result.topology.segments, (0, 4)):
            assert not part.closed and part.count == 3
            actual = result.positions[part.start : part.start + part.count]
            assert set(map(tuple, actual)) == {(x, 1, 0), (x, 2, 0), (x, 3, 0)}


@pytest.mark.parametrize(
    "center,size,reason",
    [
        ((2, 2, 0), (2.2, 10, 1), "target_ambiguous"),
        ((0, 0, 0), (0.1, 0.1, 1), "insufficient_support"),
        ((50, 0, 0), (1, 1, 1), "target_not_found"),
    ],
)
def test_multiple_runs_and_single_vertex_do_not_become_success(center, size, reason):
    """两个相反边命中不能选择最长段，单点不能构造零长线段。"""
    points = np.array([(x, y, 0) for x in range(5) for y in range(5)], dtype=float)
    result = extract(
        points, extract_parameters(targets=[target("selected", center, size)])
    )
    assert result.reason == reason and result.failed_segment_id == "selected"
    assert result.topology is None and result.positions is None


def test_partial_roi_never_closes_across_excluded_vertices_and_rejects_overlap():
    """切开闭环后不得伪造闭合边，两目标不得重复占用同一个源顶点。"""
    points = np.array([(x, y, 0) for x in range(5) for y in range(5)], dtype=float)
    left = target("left", (0, 2, 0), (0.2, 2.2, 1))
    result = extract(
        points, extract_parameters(targets=[{**left, "closed": True, "role": "outer"}])
    )
    assert result.reason == "target_not_found"
    result = extract(
        points, extract_parameters(targets=[left, {**left, "segment_id": "other"}])
    )
    assert result.reason == "target_conflict" and result.positions is None


def test_section_selection_keeps_existing_interpolated_sources_only():
    """ROI 边界在 y=.4/1.6，输出已有 .5/1/1.5 顶点，不新增端点。"""
    points = np.array([(x, y, x) for x in range(3) for y in range(4)], dtype=float)
    method = dict(
        kind="section", origin=[0, 0, 0.5], normal=[0, 0, 1], numeric_tolerance=1e-10
    )
    complete = extract(
        points,
        extract_parameters(
            method=method, targets=[target("section", (0, 1, 0), (10, 10, 10))]
        ),
    )
    finite = extract(
        points,
        extract_parameters(
            method=method, targets=[target("section", (0, 1, 0), (10, 1.2, 10))]
        ),
    )
    assert finite.reason is None
    expected = (complete.positions[:, 1] >= 0.4) & (complete.positions[:, 1] <= 1.6)
    np.testing.assert_array_equal(finite.positions, complete.positions[expected])
    np.testing.assert_array_equal(finite.source_edges, complete.source_edges[expected])
    np.testing.assert_array_equal(finite.weights, complete.weights[expected])
    np.testing.assert_allclose(
        (points[finite.source_edges] * finite.weights[..., None]).sum(axis=1),
        finite.positions,
    )


def test_selection_cancellation_is_not_swallowed():
    """取消沿既有回收异常路径传播。"""

    def cancel():
        raise InterruptedError("cancel")

    with pytest.raises(InterruptedError):
        list(
            selected_runs(
                OrderedSegment(np.arange(4), True),
                [True, False, True, False],
                cancel=cancel,
            )
        )
