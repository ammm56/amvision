"""截面来源分块与独立逐面真值核对；不以显示采样验证几何。"""

import numpy as np
import pytest

from custom_nodes.metrology3d_nodes.shared.boundary_section import _endpoint_sources


def scalar_sources(local, faces, signs, dots, lines, tolerance):
    """逐面列出实测顶点和跨面源边，不使用批量索引实现。"""
    sources, relations = [], []
    for face, line in zip(faces, lines):
        candidates = []
        for vertex in face:
            if signs[vertex] == 0:
                candidates.append(((vertex, vertex), (1.0, 0.0), local[vertex]))
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            if signs[a] * signs[b] == -1:
                a, b = sorted((int(a), int(b)))
                weight = float(dots[a] / (dots[a] - dots[b]))
                candidates.append(
                    (
                        (a, b),
                        (1 - weight, weight),
                        local[a] * (1 - weight) + local[b] * weight,
                    )
                )
        if len(candidates) != 2:
            raise RuntimeError("相交类型不一致")
        pairs, weights = [], []
        for endpoint in line:
            matches = [
                item
                for item in candidates
                if np.linalg.norm(endpoint - item[2]) <= tolerance
            ]
            if len(matches) != 1:
                return None
            pairs.append(matches[0][0])
            weights.append(matches[0][1])
        sources.append(pairs)
        relations.append(weights)
    return np.asarray(sources), np.asarray(relations)


@pytest.mark.parametrize("seed", range(6))
def test_sources_match_scalar(seed):
    """实际原生求交的端点次序、三类交线及不同面顺序保持完全相同。"""
    import trimesh
    from trimesh.constants import tol
    from trimesh.intersections import mesh_plane

    rng = np.random.default_rng(seed)
    local = rng.normal(size=(15003, 3))
    local[:6000:3, 2] = 0
    local[:3000:3, 2] = 0
    local[1:3000:3, 2] = 0
    faces = np.arange(len(local)).reshape(-1, 3)
    dots = local[:, 2]
    signs = np.sign(dots).astype(np.int8)
    mesh = trimesh.Trimesh(vertices=local, faces=faces, process=False, validate=False)
    for normal in ([0, 0, 1], [0, 0, -1]):
        lines, ids = mesh_plane(mesh, normal, [0, 0, 0], return_faces=True)
        expected = scalar_sources(local, faces[ids], signs, dots, lines, tol.merge)
        result = _endpoint_sources(local, faces[ids], signs, dots, lines, tol.merge)
        assert expected is not None and result is not None
        for actual, reference in zip(result, expected):
            np.testing.assert_array_equal(actual, reference)


@pytest.mark.parametrize(
    "factor", [0.0, 1.0, np.nextafter(1.0, 0.0), np.nextafter(1.0, 2.0), 2.0]
)
def test_tolerance_boundary_retains_scalar_decision(factor):
    """包含关系使用原范数；容差边缘不靠默认相对误差放过。"""
    local = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 1]], dtype=float)
    faces = np.array([[0, 1, 2]])
    lines = local[faces[:, :2]].copy()
    tolerance = 1e-8
    lines[:, 0, 2] += factor * tolerance
    dots = local[:, 2]
    args = (local, faces, np.sign(dots).astype(np.int8), dots, lines, tolerance)
    expected, actual = scalar_sources(*args), _endpoint_sources(*args)
    assert (actual is None) == (expected is None)
    if actual is not None:
        for result, reference in zip(actual, expected):
            np.testing.assert_array_equal(result, reference)


def test_ambiguous_and_inconsistent_sources_fail():
    """两个候选均命中时无效；原生线与源面类型不一致仍为执行错误。"""
    local = np.array([[0, 0, 0], [1e-9, 0, 0], [0, 2, 1]], dtype=float)
    faces = np.array([[0, 1, 2]])
    dots = local[:, 2]
    lines = local[faces[:, :2]]
    assert (
        _endpoint_sources(
            local, faces, np.sign(dots).astype(np.int8), dots, lines, 1e-8
        )
        is None
    )
    with pytest.raises(RuntimeError, match="相交类型不一致"):
        _endpoint_sources(local, faces, np.zeros(3, dtype=np.int8), dots, lines, 1e-8)


@pytest.mark.parametrize("cancel_after_block", [False, True])
def test_matching_blocks_remain_bounded_and_cancellable(
    monkeypatch, cancel_after_block
):
    """超过一个块的实测三角面全部保留，取消不能返回部分成功截线。"""
    from custom_nodes.metrology3d_nodes.shared import boundary_section as module

    count = 5000
    points = np.tile([[0, 0, -1], [2, 0, 1], [0, 2, 1]], (count, 1)).astype(float)
    points[:, 0] += np.repeat(np.arange(count) * 3, 3)
    faces = np.arange(count * 3).reshape(-1, 3)
    sizes = []
    original = module._endpoint_sources

    def match(*args):
        sizes.append(len(args[1]))
        return original(*args)

    def cancel():
        if cancel_after_block and sizes:
            raise InterruptedError("matching-block-cancelled")

    monkeypatch.setattr(module, "_endpoint_sources", match)
    arguments = dict(
        origin=[0, 0, 0],
        normal=[0, 0, 1],
        numeric_tolerance=1e-10,
        max_working_bytes=64 * 1024 * 1024,
        cancel=cancel,
    )
    if cancel_after_block:
        with pytest.raises(InterruptedError, match="matching-block-cancelled"):
            module.intersect_surface(points, faces, **arguments)
        assert sizes == [4096]
    else:
        result = module.intersect_surface(points, faces, **arguments)
        assert result.reason is None and len(result.edges) == count
        assert sizes == [4096, 904, 4096, 904]
        np.testing.assert_array_equal(result.face_indices, np.arange(count))
