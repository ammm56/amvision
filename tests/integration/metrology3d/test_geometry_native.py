"""显式原生几何验收；缺 Open3D 或版本不符直接失败，不静默跳过。"""

import numpy as np
import pytest
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from tests.point_cloud_support import policy
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud


def test_ransac_refits_and_preserves_original_inlier_rows():
    """真实 Open3D 候选、正交重拟合及内点原始行号。"""
    import open3d

    assert open3d.__version__ == "0.20.0"
    grid = np.array([(x, y, 5) for x in range(8) for y in range(8)], dtype=np.float32)
    points = np.concatenate(([[0, 0, 30]], grid, [[1, 1, -20]])).astype(np.float32)
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=131072, max_live_array_bytes=131072),
    )
    try:
        p = plane_parameters(
            algorithm=dict(
                kind="ransac-svd",
                distance_threshold=0.01,
                sample_size=3,
                iterations=100,
                probability=0.999,
            )
        )
        result = fit_plane(runtime, cloud, p, cancel=lambda: None)
        feature = result.items[0]
        assert feature.valid and feature.support.point_count == 64
        assert feature.geometry.offset == pytest.approx(-5, abs=1e-12)
        assert (
            feature.support.provenance.method.indices_sha256
            == sha256(np.arange(1, 65, dtype="<u4").tobytes()).hexdigest()
        )
        with runtime.borrow(feature.support) as view:
            np.testing.assert_array_equal(view.source_indices(0, 2), [1, 2])
        assert runtime.source_point_count(feature.support) == 66
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def native_case(dtype, plane, cancel=lambda: None):
    """独立解析平面与显式外点，不用拟合器生成期望几何。"""
    xy = np.array([(x, y) for x in range(8) for y in range(8)], dtype=dtype)
    if plane == "vertical":
        grid = np.column_stack((np.full(64, 5), xy))
        normal, offset = np.array([1.0, 0.0, 0.0]), -5.0
    else:
        grid = np.column_stack((xy, 5 + xy[:, 0] / 2 - xy[:, 1] / 4))
        normal, offset = np.array([-2.0, 1.0, 4.0]) / np.sqrt(21), -20 / np.sqrt(21)
    points = np.concatenate(
        ([grid[0] + normal * 20], grid, [grid[-1] - normal * 20])
    ).astype(dtype)
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=262144, max_live_array_bytes=131072),
    )
    try:
        result = fit_plane(
            runtime,
            cloud,
            plane_parameters(
                positive_normal=normal.tolist(),
                algorithm=dict(
                    kind="ransac-svd",
                    distance_threshold=0.001,
                    sample_size=3,
                    iterations=100,
                    probability=0.999,
                ),
            ),
            cancel=cancel,
        )
        feature = result.items[0]
        assert feature.valid, feature.reason
        np.testing.assert_allclose(feature.geometry.normal, normal, atol=1e-12)
        assert feature.geometry.offset == pytest.approx(offset, abs=1e-12)
        assert feature.support.point_count == 64
        with runtime.borrow(feature.support) as view:
            for start in range(0, 64, 2):
                np.testing.assert_array_equal(
                    view.source_indices(start, start + 2), [start + 1, start + 2]
                )
        return feature.geometry
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("plane", ["vertical", "inclined"])
def test_native_independent_truth(dtype, plane):
    """真实候选/重拟合覆盖源精度、竖直面、倾斜面及原始行号。"""
    native_case(dtype, plane)


@pytest.mark.parametrize("kind", ["line", "coincident"])
def test_native_degenerate_support_is_invalid(kind):
    """原生退化结果不能变成有效几何，也不能遗留数组计费。"""
    points = np.zeros((16, 3), dtype=np.float64)
    if kind == "line":
        points[:, 0] = np.arange(16)
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=262144, max_live_array_bytes=131072),
    )
    try:
        feature = fit_plane(
            runtime,
            cloud,
            plane_parameters(
                algorithm=dict(
                    kind="ransac-svd",
                    distance_threshold=0.001,
                    sample_size=3,
                    iterations=100,
                    probability=0.999,
                )
            ),
            cancel=lambda: None,
        ).items[0]
        assert not feature.valid and feature.geometry is None
        assert feature.reason is not None
        assert feature.support.point_count == 0
        assert (
            feature.support.provenance.method.indices_sha256 == sha256(b"").hexdigest()
        )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_native_centering_overflow_rejected_without_retained_arrays():
    """有限源坐标相减溢出不得把 Inf 送入原生候选，计费保持不变。"""
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[1e308, 0, 0], [-1e308, 1, 0], [0, 1, 1]]),
        runtime_policy=policy(max_working_bytes=262144, max_live_array_bytes=131072),
    )
    before = runtime.budget.used
    try:
        with pytest.raises(FloatingPointError, match="overflow"):
            fit_plane(
                runtime,
                cloud,
                plane_parameters(
                    algorithm=dict(
                        kind="ransac-svd",
                        distance_threshold=0.001,
                        sample_size=3,
                        iterations=100,
                        probability=0.999,
                    )
                ),
                cancel=lambda: None,
            )
        assert runtime.budget.used == before
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_native_repeated_and_concurrent_runs_are_isolated():
    """每次独立 Scope；不重置 Open3D 全局 RNG，也不加串行排队锁。"""
    for _ in range(4):
        native_case(np.float32, "inclined")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: native_case(np.float64, "vertical"), range(8))
        )
    assert len(results) == 8


def test_native_cancellation_releases_scope():
    """真实原生调用前后及重拟合阶段的取消都能关闭同一 Scope。"""
    calls = 0

    def count():
        nonlocal calls
        calls += 1

    native_case(np.float64, "inclined", count)
    total = calls
    for boundary in (1, 2, total // 2, total - 1, total):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == boundary:
                raise InterruptedError("native acceptance cancellation")

        with pytest.raises(InterruptedError):
            native_case(np.float64, "inclined", cancel)
