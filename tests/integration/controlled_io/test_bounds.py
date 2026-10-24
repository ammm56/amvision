"""受控 trimesh 同一凸包边方向算法的独立真值、并列和资源回归。"""

import numpy as np
import pytest
from scipy.spatial import QhullError
from trimesh.bounds import oriented_bounds_2D


def candidates(points, **changes):
    """显式测试容量与比较容差，不作为生产参数。"""
    return oriented_bounds_2D(
        points,
        **{
            "max_working_bytes": 1_000_000,
            "cancel": lambda: None,
            "area_abs_tolerance": 1e-12,
            "area_rel_tolerance": 1e-12,
            "return_candidates": True,
            **changes,
        },
    )


@pytest.mark.parametrize("angle", [0, 0.37, 1.4])
def test_rotated_rectangle_matches_analytic_extents_and_contains_input(angle):
    """已知矩形的长宽不由被测函数生成；内部点不改变包络。"""
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    )
    points = np.array(
        [[-3, -1], [3, -1], [3, 1], [-3, 1], [0, 0]], dtype=float
    ) @ rotation.T + [13, -7]
    transform, extents, evidence = candidates(points)
    standard_transform, standard_extents = oriented_bounds_2D(points)
    np.testing.assert_array_equal(standard_transform, transform)
    np.testing.assert_array_equal(standard_extents, extents)
    np.testing.assert_allclose(extents, [6, 2], atol=1e-12)
    np.testing.assert_allclose(evidence["minimum_area"], 12, atol=1e-12)
    transformed = points @ transform[:2, :2].T + transform[:2, 2]
    np.testing.assert_allclose(transformed.min(axis=0), -extents / 2, atol=1e-12)
    np.testing.assert_allclose(transformed.max(axis=0), extents / 2, atol=1e-12)
    assert len(evidence["areas"]) == 4
    for bounds, axis, size in zip(
        evidence["bounds"], evidence["axes"], evidence["extents"]
    ):
        axes = np.array([axis, [-axis[1], axis[0]]])
        projected = points @ axes.T
        np.testing.assert_allclose(projected.min(axis=0), bounds[:2], atol=1e-12)
        np.testing.assert_allclose(projected.max(axis=0), bounds[2:], atol=1e-12)
        np.testing.assert_allclose(size, bounds[2:] - bounds[:2])


def test_triangle_keeps_all_equal_area_rectangles_with_different_dimensions():
    """直角三角形三个边向包络等面积，不能只返回 argmin 的长宽。"""
    _, _, evidence = candidates(np.array([[0, 0], [4, 0], [0, 3]], dtype=float))
    np.testing.assert_allclose(evidence["areas"], [12, 12, 12], atol=1e-12)
    sizes = np.sort(evidence["extents"], axis=1)
    assert any(np.allclose(size, [3, 4]) for size in sizes)
    assert any(np.allclose(size, [2.4, 5]) for size in sizes)


def test_square_keeps_equal_dimensions_without_inventing_a_unique_long_axis():
    _, _, evidence = candidates(
        np.array([[-2, -2], [2, -2], [2, 2], [-2, 2]], dtype=float)
    )
    np.testing.assert_allclose(evidence["extents"], np.full((4, 2), 4), atol=1e-12)


def test_blocked_projection_matches_independent_enumeration_and_checks_both_passes():
    """小规模逐边独立投影核对最优性；预算只改变分块，不改变结果。"""
    theta = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    points = np.column_stack((np.cos(theta) * 3, np.sin(theta)))
    calls = []
    _, expected_size, expected = candidates(points)
    _, actual_size, actual = candidates(
        points, max_working_bytes=23000, cancel=lambda: calls.append(1)
    )
    np.testing.assert_array_equal(actual_size, expected_size)
    for key in ("areas", "axes", "extents", "indices", "bounds"):
        np.testing.assert_array_equal(actual[key], expected[key])
    assert len(calls) > 6
    independently = []
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        direction = (b - a) / np.linalg.norm(b - a)
        perpendicular = np.array([-direction[1], direction[0]])
        u = [float(np.dot(p, direction)) for p in points]
        v = [float(np.dot(p, perpendicular)) for p in points]
        independently.append((max(u) - min(u)) * (max(v) - min(v)))
    assert actual["minimum_area"] == pytest.approx(min(independently), abs=1e-12)
    np.testing.assert_array_equal(
        points, np.column_stack((np.cos(theta) * 3, np.sin(theta)))
    )


def test_ties_use_final_minimum_and_are_permutation_independent():
    points = np.array([[0, 0], [5, 0], [4, 2], [1, 3], [-1, 1]], dtype=float)
    evidence = candidates(points, area_abs_tolerance=0.5)[2]
    for order in (np.arange(len(points))[::-1], [2, 4, 1, 0, 3]):
        other = candidates(points[order], area_abs_tolerance=0.5)[2]
        np.testing.assert_allclose(sorted(evidence["areas"]), sorted(other["areas"]))
    assert np.all(evidence["areas"] - evidence["minimum_area"] <= 0.5)


def test_budget_cancel_and_degenerate_input_never_fall_back():
    points = np.array([[0.0, 0.0], [1, 0], [0, 1]])
    with pytest.raises(MemoryError):
        candidates(points, max_working_bytes=1)

    class Cancelled(Exception):
        pass

    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 5:
            raise Cancelled

    with pytest.raises(Cancelled):
        candidates(points, cancel=cancel)
    for invalid in (np.full((3, 2), np.nan), np.full((3, 2), np.inf)):
        with pytest.raises(ValueError, match="finite"):
            candidates(invalid)
    with pytest.raises(QhullError):
        candidates(np.array([[0.0, 0.0], [1, 1], [2, 2]]))
    with pytest.raises(ValueError, match="perturbation"):
        candidates(points, qhull_options="QJ")
    for missing in (
        "max_working_bytes",
        "cancel",
        "area_abs_tolerance",
        "area_rel_tolerance",
    ):
        with pytest.raises(ValueError, match="explicit"):
            candidates(points, **{missing: None})


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("scale", [1e-6, 1.0, 1e6])
def test_declared_precision_and_physical_scale(dtype, scale):
    """直接矩形在 m/mm 等尺度下保持原输入精度，不偷偷改变输入。"""
    points = (np.array([[0, 0], [6, 0], [6, 2], [0, 2]]) * scale).astype(dtype)
    before = points.tobytes()
    _, size, evidence = candidates(points, area_abs_tolerance=1e-24)
    np.testing.assert_allclose(size, [6 * scale, 2 * scale], rtol=2e-7)
    assert evidence["candidate_count"] == 4
    assert points.dtype == dtype and points.tobytes() == before


def test_strict_candidate_path_rejects_implicit_precision_loss():
    for dtype in (np.float16, np.int64, np.complex128):
        with pytest.raises(ValueError, match="float32 or float64"):
            candidates(np.array([[0, 0], [1, 0], [0, 1]], dtype=dtype))
