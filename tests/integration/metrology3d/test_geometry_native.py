"""显式原生几何验收；缺 Open3D 或版本不符直接失败，不静默跳过。"""

import numpy as np
import pytest

from custom_nodes._metrology3d_nodes.shared.fit_plane import fit_plane
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
        with runtime.borrow(feature.support) as view:
            np.testing.assert_array_equal(view.source_indices(0, 2), [1, 2])
        assert runtime.source_point_count(feature.support) == 66
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
