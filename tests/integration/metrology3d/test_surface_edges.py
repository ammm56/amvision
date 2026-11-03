"""边排序优化的独立拓扑真值；不改变三角剖分、面筛选或质量门禁。"""

import numpy as np
import pytest

from custom_nodes.metrology3d_nodes.shared.boundary_surface import _boundary_edges


def scalar_edges(faces):
    """逐边字典分组并保留输入方向，独立于 NumPy 排序实现。"""
    grouped = {}
    for pair in ((0, 1), (1, 2), (2, 0)):
        for face in faces:
            edge = tuple(int(face[i]) for i in pair)
            grouped.setdefault(tuple(sorted(edge)), []).append(edge)
    if any(len(values) > 2 for values in grouped.values()):
        return None
    return np.array(
        [values[0] for _, values in sorted(grouped.items()) if len(values) == 1],
        dtype=np.int64,
    ).reshape(-1, 2)


@pytest.mark.parametrize("seed", range(12))
def test_edges_match_scalar_topology_order_and_orientation(seed):
    """含稀疏大行号、换序、反向、共享边及非流形输入。"""
    rng = np.random.default_rng(seed)
    faces = np.array([[i, i + 1, i + 8] for i in range(30)], dtype=np.int64)
    faces *= 10**12
    if seed % 3 == 0:
        faces = np.concatenate((faces, faces[:2], faces[:1]))
    faces = faces[rng.permutation(len(faces))]
    faces[::2] = faces[::2, ::-1]
    before = faces.copy()
    expected = scalar_edges(faces)
    result = _boundary_edges(faces, cancel=lambda: None)
    if expected is None:
        assert result is None
    else:
        np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(faces, before)


def test_empty_closed_surface_and_cancellation():
    """空边、闭合四面体以及每个可取消阶段均不泄露部分结果。"""
    for faces in (
        np.empty((0, 3), dtype=np.int64),
        np.array([[0, 1, 2], [0, 3, 1], [0, 2, 3], [1, 3, 2]]),
    ):
        assert _boundary_edges(faces, cancel=lambda: None).shape == (0, 2)
    for at in range(1, 4):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == at:
                raise InterruptedError("stop")

        with pytest.raises(InterruptedError):
            _boundary_edges(np.array([[0, 1, 2]]), cancel=cancel)
