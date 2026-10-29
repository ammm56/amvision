"""边界工作集回归：独立逐面真值、取消、临时数组寿命和预算拒绝。"""

import weakref

import numpy as np
import pytest
from scipy.spatial import Delaunay

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
    materialize_positions,
)
from custom_nodes.metrology3d_nodes.shared.boundary_surface import build_surface
from tests.integration.metrology3d.test_boundary_surface_topology import surface
from tests.point_cloud_support import policy
from tests.test_metrology3d_preprocess import make_cloud


def grid(dtype):
    """非规则、带高度台阶的完整测试点集，不是生产采样。"""
    xy = np.random.default_rng(20261026).uniform(-4, 4, (5000, 2))
    z = 0.02 * xy[:, 0] + np.where(xy[:, 1] > 0, 0.4, 0)
    return np.column_stack((xy, z)).astype(dtype)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_surface_matches_independent_face_truth(dtype):
    """逐面标量计算四个约束，保持 Qhull 面次序及真实边界方向。"""
    points = grid(dtype)
    snapshot = points.copy()
    triangles = Delaunay(points[:, :2].astype(float)).simplices
    expected = []
    for face in triangles:
        p = points[face].astype(float)
        a, b, c = p[:, :2]
        lengths = [np.linalg.norm(a - b), np.linalg.norm(b - c), np.linalg.norm(c - a)]
        u, v = b - a, c - a
        area2 = abs(u[0] * v[1] - u[1] * v[0])
        if (
            area2 >= 0.0002
            and np.prod(lengths) / (2 * area2) <= 0.15
            and max(lengths) <= 0.3
            and max(p[:, 2]) - min(p[:, 2]) <= 0.1
        ):
            expected.append(face)
    result = surface(
        points,
        alpha_radius=0.15,
        max_edge_length=0.3,
        max_normal_step=0.1,
        min_projected_area=0.0001,
        max_working_bytes=32 * 1024 * 1024,
    )
    assert result.reason is None
    np.testing.assert_array_equal(result.faces, expected)
    edge_counts = {}
    for a, b, c in expected:
        for edge in ((a, b), (b, c), (c, a)):
            key = tuple(sorted(edge))
            edge_counts[key] = edge_counts.get(key, 0) + 1
    assert {tuple(sorted(e)) for e in result.boundary_edges} == {
        e for e, count in edge_counts.items() if count == 1
    }
    np.testing.assert_array_equal(points, snapshot)


def test_surface_releases_qhull_and_bounds_filter_blocks(monkeypatch):
    """筛选期间不保留剖分对象，不分配完整三角面数的 sides 数组。"""
    mesh_refs, block_sizes = [], []
    original_norm = np.linalg.norm

    def triangulate(*args, **kwargs):
        mesh = Delaunay(*args, **kwargs)
        mesh_refs.append(weakref.ref(mesh))
        return mesh

    def norm(values, *args, **kwargs):
        if values.ndim == 3 and values.shape[1:] == (3, 2):
            assert mesh_refs and mesh_refs[-1]() is None
            block_sizes.append(len(values))
        return original_norm(values, *args, **kwargs)

    monkeypatch.setitem(build_surface.__globals__, "Delaunay", triangulate)
    monkeypatch.setattr(np.linalg, "norm", norm)
    result = surface(grid(np.float32), max_working_bytes=32 * 1024 * 1024)
    assert result.reason is None
    assert len(block_sizes) >= 3 and max(block_sizes) <= 4096
    assert sum(block_sizes) == result.candidate_face_count


def test_surface_cancellation_during_face_filter(monkeypatch):
    """进入筛选后仍响应取消；不必等待全量边构造完成。"""
    block_sizes = []
    original_norm = np.linalg.norm

    def norm(values, *args, **kwargs):
        if values.ndim == 3:
            block_sizes.append(len(values))
        return original_norm(values, *args, **kwargs)

    def cancel():
        if block_sizes:
            raise InterruptedError("face-filter-cancelled")

    monkeypatch.setattr(np.linalg, "norm", norm)
    with pytest.raises(InterruptedError, match="face-filter-cancelled"):
        surface(grid(np.float32), max_working_bytes=32 * 1024 * 1024, cancel=cancel)
    assert block_sizes == [4096]


def test_materialize_budget_has_actionable_details_before_allocation(monkeypatch):
    """预算错误不引导删掉物理支持；错误保留阶段、点数和需求值。"""
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="f4"),
        runtime_policy=policy(max_working_bytes=32768),
    )
    before = runtime.budget.used

    def forbidden(*args, **kwargs):
        pytest.fail("预算不足时不能分配物化数组")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(np, "empty", forbidden)
            with pytest.raises(InvalidRequestError) as raised:
                materialize_positions(
                    runtime, cloud, factor=12544, with_sources=True, cancel=lambda: None
                )
        assert raised.value.details == dict(
            stage="materialize_positions",
            point_count=3,
            estimated_bytes=37632,
            limit_bytes=32768,
        )
        assert "37632" in str(raised.value) and "32768" in str(raised.value)
        assert "缩小 ROI" not in str(raised.value)
        assert runtime.budget.used == before
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize(
    "stage,factor", [("build_surface", 2048), ("extract_boundary_array", 12288)]
)
def test_kernel_capacity_error_identifies_stage(stage, factor):
    """直接数组入口也保留同一错误分类和可定位容量信息。"""
    from tests.integration.metrology3d.test_boundary_extraction import extract

    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="f4")
    with pytest.raises(InvalidRequestError) as raised:
        (surface if stage == "build_surface" else extract)(points, max_working_bytes=1)
    assert raised.value.details == dict(
        stage=stage, point_count=3, estimated_bytes=3 * factor, limit_bytes=1
    )
