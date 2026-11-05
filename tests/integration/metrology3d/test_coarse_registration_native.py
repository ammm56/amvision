"""B04 粗定位的锁定原生库边界；不代替公开节点或多解验收。"""

import numpy as np
from scipy.spatial.transform import Rotation


def cloud(points, normals=None):
    """仅构造原生输入，不读写项目运行资源。"""
    import open3d as o3d

    result = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    if normals is not None:
        result.normals = o3d.utility.Vector3dVector(normals)
    return result


def test_mutual_correspondences_must_explicitly_disable_upstream_fallback():
    """默认 10% 会回退单向；显式零阈值保留不足的真实双向对应。"""
    import open3d as o3d

    reg = o3d.pipelines.registration
    source, target = reg.Feature(), reg.Feature()
    source.data = np.arange(100, dtype=np.float64)[None, :]
    target.data = np.array([[0.0, 99.0]])
    fallback = np.asarray(reg.correspondences_from_features(source, target, True))
    strict = np.asarray(reg.correspondences_from_features(source, target, True, 0.0))
    assert len(fallback) == 100
    np.testing.assert_array_equal(strict, [[0, 0], [99, 1]])


def test_fpfh_uses_provided_normals_and_is_rigid_invariant():
    """完整支持、已有法向随独立真值变换，不能在入口暗中重新估计。"""
    import open3d as o3d

    rng = np.random.default_rng(20261105)
    points = rng.normal(size=(160, 3)) * [1, 2, 3]
    normals = rng.normal(size=points.shape)
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    rotation = Rotation.from_euler("xyz", [37, -22, 81], degrees=True).as_matrix()
    shifted = points @ rotation.T + [5, -8, 11]
    source, target = cloud(points, normals), cloud(shifted, normals @ rotation.T)
    search = o3d.geometry.KDTreeSearchParamHybrid(radius=3.0, max_nn=30)
    a = np.asarray(o3d.pipelines.registration.compute_fpfh_feature(source, search).data)
    b = np.asarray(o3d.pipelines.registration.compute_fpfh_feature(target, search).data)
    assert a.shape == (33, len(points)) and np.isfinite(a).all()
    np.testing.assert_allclose(a, b, rtol=0, atol=1e-10)
    np.testing.assert_array_equal(source.points, points)
    np.testing.assert_array_equal(source.normals, normals)


def test_ransac_explicit_correspondences_preserve_rigid_truth():
    """复用上游求解，不自行实现 RANSAC；独立真值包含大角度和平移。"""
    import open3d as o3d

    points = np.random.default_rng(5).normal(size=(24, 3)) * [1, 2, 3]
    rotation = Rotation.from_euler("xyz", [37, -22, 81], degrees=True).as_matrix()
    translation = np.array([5, -8, 11])
    target = points @ rotation.T + translation
    reg = o3d.pipelines.registration
    pairs = o3d.utility.Vector2iVector(np.column_stack((np.arange(24), np.arange(24))))
    result = reg.registration_ransac_based_on_correspondence(
        cloud(points),
        cloud(target),
        pairs,
        1e-6,
        reg.TransformationEstimationPointToPoint(with_scaling=False),
        3,
        [reg.CorrespondenceCheckerBasedOnEdgeLength(0.99)],
        reg.RANSACConvergenceCriteria(64, 1.0),
    )
    expected = np.eye(4)
    expected[:3, :3], expected[:3, 3] = rotation, translation
    assert len(result.correspondence_set) == len(points)
    assert result.fitness == 1.0
    np.testing.assert_allclose(result.transformation, expected, rtol=0, atol=1e-12)


def test_ransac_empty_correspondences_return_identity_but_not_success():
    """上游默认单位阵和零 RMS 不能用作平台成功判据。"""
    import open3d as o3d

    reg = o3d.pipelines.registration
    points = np.eye(3)
    result = reg.registration_ransac_based_on_correspondence(
        cloud(points),
        cloud(points + 10),
        o3d.utility.Vector2iVector(np.empty((0, 2), dtype=np.int32)),
        0.01,
        reg.TransformationEstimationPointToPoint(with_scaling=False),
        3,
        [],
        reg.RANSACConvergenceCriteria(8, 1.0),
    )
    assert not len(result.correspondence_set)
    assert result.fitness == 0 and result.inlier_rmse == 0
    np.testing.assert_array_equal(result.transformation, np.eye(4))
