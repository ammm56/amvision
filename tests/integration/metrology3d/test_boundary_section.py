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


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("scale,offset", [(1.0, 0.0), (0.001, 0.0), (1.0, 1e6)])
@pytest.mark.parametrize("tilted", [False, True])
def test_cached_candidates_match_all_native_faces(
    monkeypatch, sign, scale, offset, tilted
):
    """比较同一库的完整面集，含容差等号、相邻浮点数、共面边与正反法向。"""
    import trimesh.intersections

    rng = np.random.default_rng(36)
    points = rng.uniform(-2, 2, (300, 3))
    normal = np.array([0.0, 0.0, 1.0])
    tolerance = 1e-8 * scale
    points[:9, 2] = np.tile([1e-8, -1e-8, 0.0], 3)
    points[9:18, 2] = np.tile([np.nextafter(1e-8, np.inf), -1.0, 1.0], 3)
    # 防止人为添加整片共面区域，使两向库调用确实被比较。
    points[:9:3, 2] = 1.0
    if tilted:
        from scipy.spatial.transform import Rotation

        rotation = Rotation.from_rotvec([0.3, -0.6, 0.2]).as_matrix()
        points = points @ rotation.T
        normal = rotation @ normal
    origin = np.full(3, offset)
    points = points * scale + origin
    original = trimesh.intersections.mesh_plane
    observed = []

    def audited(mesh, direction, origin, **kwargs):
        actual = original(mesh, direction, origin, **kwargs)
        expected = original(mesh, direction, origin, return_faces=True)
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_array_equal(actual[1], expected[1])
        observed.append(len(kwargs["local_faces"]))
        assert len(kwargs["local_faces"]) < len(mesh.faces)
        return actual

    monkeypatch.setattr(trimesh.intersections, "mesh_plane", audited)
    result = intersect_surface(
        points,
        np.arange(300).reshape(-1, 3),
        origin=origin,
        normal=normal * sign,
        numeric_tolerance=tolerance,
        max_working_bytes=1048576,
        cancel=lambda: None,
    )
    assert result.reason is None
    assert len(observed) == 2


def test_off_plane_degenerate_faces_are_not_removed_by_candidate_filter():
    """严格同侧的坏面仍必须参与全表面合法性判断。"""
    result = section(
        [[0, 0, -1], [2, 0, 1], [0, 2, 1], [0, 0, 5], [1, 0, 5], [2, 0, 5]],
        faces=((0, 1, 2), (3, 4, 5)),
    )
    assert result.reason == "degenerate_surface"
