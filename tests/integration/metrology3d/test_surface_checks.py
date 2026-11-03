"""建面检查的独立逐行真值、原顺序、取消及完整局部输入对照。"""

import numpy as np
import pytest

from custom_nodes.metrology3d_nodes.shared.boundary_surface import (
    _boundary_edges,
    _covers_vertices,
    _has_duplicate_projection,
)


@pytest.mark.parametrize("offset", [0, 2**32 - 6, 2**32, 2**53])
@pytest.mark.parametrize("nonmanifold", [False, True])
def test_edge_storage_preserves_scalar_groups_and_direction(offset, nonmanifold):
    """独立字典真值覆盖整数宽度边界、首条方向和多面共享拒绝。"""
    faces = np.array([[0, 1, 2], [1, 0, 3], [2, 1, 4], [4, 1, 5]], dtype=np.int64)
    if nonmanifold:
        faces = np.concatenate((faces, [[0, 1, 5]]))
    faces += offset
    before = faces.copy()
    groups = {}
    for a, b in ((0, 1), (1, 2), (2, 0)):
        for face in faces:
            edge = (int(face[a]), int(face[b]))
            groups.setdefault(tuple(sorted(edge)), []).append(edge)
    result = _boundary_edges(faces, cancel=lambda: None)
    if nonmanifold:
        assert result is None
    else:
        expected = [edges[0] for _, edges in sorted(groups.items()) if len(edges) == 1]
        np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(faces, before)


def test_edge_storage_empty_and_cancellation():
    """空面与排序前后取消不能产生部分边界。"""
    faces = np.empty((0, 3), dtype=np.int64)
    assert _boundary_edges(faces, cancel=lambda: None).shape == (0, 2)
    faces = np.arange(9000, dtype=np.int64).reshape(-1, 3)
    for at in range(1, 5):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == at:
                raise InterruptedError("cancel")

        with pytest.raises(InterruptedError):
            _boundary_edges(faces, cancel=cancel)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("seed", range(8))
def test_projection_duplicate_matches_scalar_and_preserves_input(dtype, seed):
    """正负零数值相等，近邻不合并；支持非连续视图和换序。"""
    rng = np.random.default_rng(seed)
    xy = rng.normal(size=(10003, 4)).astype(dtype)[:, ::2]
    xy[0], xy[-1] = (0.0, -0.0), (-0.0, 0.0 if seed % 2 else 1e-30)
    before = xy.copy()
    expected = len({tuple(row) for row in xy}) != len(xy)
    assert _has_duplicate_projection(xy, cancel=lambda: None) == expected
    np.testing.assert_array_equal(xy, before)


@pytest.mark.parametrize("missing", [False, True])
def test_vertex_coverage_matches_scalar(missing):
    """共享、重复、反向及块尾面不改变顶点覆盖含义。"""
    triangles = np.arange(27003, dtype=np.int32).reshape(-1, 3)
    triangles = np.concatenate((triangles[::-1], triangles[:10]))
    if missing:
        triangles[triangles == 27002] = 27001
    before = triangles.copy()
    expected = len({int(i) for face in triangles for i in face}) == 27003
    assert _covers_vertices(triangles, 27003, cancel=lambda: None) == expected
    np.testing.assert_array_equal(triangles, before)
    assert not _covers_vertices(np.empty((0, 3), dtype=int), 3, cancel=lambda: None)


@pytest.mark.parametrize("operation", ["projection", "coverage"])
@pytest.mark.parametrize("at", [1, 2, 3, 4])
def test_surface_checks_cancel(operation, at):
    """排序前后和分块中止继续传播，不返回部分成功结果。"""
    count = 0

    def cancel():
        nonlocal count
        count += 1
        if count == at:
            raise InterruptedError("cancel")

    with pytest.raises(InterruptedError):
        if operation == "projection":
            _has_duplicate_projection(np.arange(30000).reshape(-1, 2), cancel=cancel)
        else:
            _covers_vertices(np.arange(30000).reshape(-1, 3), 30000, cancel=cancel)
