"""截面真实库验证；解析交点不由被测算法生成，数值仅用于测试。"""

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.boundary_section import intersect_surface


def section(points, faces=((0, 1, 2),), *, sign=1, scale=1, **changes):
    """同一几何用显式 mm/m 数值与正反法向调用。"""
    options = dict(
        origin=[0, 0, 0],
        normal=[0, 0, sign],
        numeric_tolerance=1e-10 * scale,
        max_working_bytes=1048576,
        cancel=lambda: None,
    )
    options.update(changes)
    return intersect_surface(
        np.asarray(points, dtype=np.float64) * scale,
        np.asarray(faces, dtype=np.int64),
        **options,
    )


def positions(result):
    """不以库输出端点次序定义期望几何。"""
    return sorted(map(tuple, result.positions))


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("scale", [1, 0.001])
@pytest.mark.parametrize(
    "points, expected",
    [
        ([[0, 0, -1], [2, 0, 1], [0, 2, 1]], [(0, 1, 0), (1, 0, 0)]),
        ([[0, 0, 0], [2, 0, -1], [0, 2, 1]], [(0, 0, 0), (1, 1, 0)]),
        ([[0, 0, 0], [2, 0, 0], [0, 2, 1]], [(0, 0, 0), (2, 0, 0)]),
    ],
)
def test_section_analytic_endpoints_and_source_weights(sign, scale, points, expected):
    """穿面、穿顶点、共面边均不随法向反转消失，来源可独立重建。"""
    result = section(points, sign=sign, scale=scale)
    assert result.reason is None
    np.testing.assert_allclose(
        positions(result), np.array(expected) * scale, atol=1e-13
    )
    restored = (
        np.asarray(points)[result.source_vertices] * result.weights[..., None]
    ).sum(axis=1) * scale
    np.testing.assert_allclose(result.positions, restored, atol=1e-13)
    np.testing.assert_array_equal(result.face_indices, [0])
    np.testing.assert_array_equal(result.face_offsets, [0, 1])
    assert result.edges.shape == (1, 2)


@pytest.mark.parametrize(
    "points,reason",
    [
        ([[0, 0, 0], [2, 0, 0], [0, 2, 0]], "coplanar_region"),
        ([[0, 0, 1], [2, 0, 1], [0, 2, 1]], "no_intersection"),
        ([[0, 0, 0], [2, 0, 1], [0, 2, 1]], "no_intersection"),
        ([[0, 0, -1], [0, 0, 0], [0, 0, 1]], "degenerate_surface"),
    ],
)
def test_coplanar_region_tangent_and_degeneracy_are_not_fake_lines(points, reason):
    """二维共面区域、单点相切及退化不冒充一维截面。"""
    for sign in (1, -1):
        result = section(points, sign=sign)
        assert result.reason == reason
        assert not len(result.positions) and not len(result.edges)


def test_shared_edge_is_not_duplicated_and_distant_same_coordinates_are_not_joined():
    """按源边去重，不因坐标相同将两个不同来源的片连接。"""
    points = [[0, 0, 0], [2, 0, 0], [0, 2, 1], [0, -2, -1]]
    result = section(points, [(0, 1, 2), (1, 0, 3)])
    assert result.reason is None and result.edges.shape == (1, 2)
    np.testing.assert_array_equal(result.face_offsets, [0, 2])
    np.testing.assert_array_equal(result.face_indices, [0, 1])
    result = section(points + points[:3], [(0, 1, 2), (4, 5, 6)])
    assert result.reason is None and result.edges.shape == (2, 2)
    assert len(result.positions) == 4


def test_cancel_budget_and_native_error_are_not_missing_geometry(monkeypatch):
    """预算、取消及原生异常保持执行错误，不伪装缺测或切换内核。"""
    import trimesh.intersections

    points = np.array([[0, 0, -1], [2, 0, 1], [0, 2, 1]], dtype=float)

    def invoke(**changes):
        options = dict(
            origin=[0, 0, 0],
            normal=[0, 0, 1],
            numeric_tolerance=1e-10,
            max_working_bytes=1048576,
            cancel=lambda: None,
        )
        options.update(changes)
        return intersect_surface(points, np.array([[0, 1, 2]]), **options)

    with pytest.raises(InvalidRequestError, match="预算"):
        invoke(max_working_bytes=1)

    def cancelled():
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        invoke(cancel=cancelled)

    def failed(*args, **kwargs):
        raise RuntimeError("native failure")

    monkeypatch.setattr(trimesh.intersections, "mesh_plane", failed)
    with pytest.raises(RuntimeError, match="native failure"):
        invoke()
