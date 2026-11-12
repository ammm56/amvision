"""Open3D 0.20 原生配准边界；不把库返回值直接视为平台有效位姿。"""

import numpy as np
import pytest
import open3d as o3d
from scipy.spatial.transform import Rotation


def native_cloud(points, normals=None):
    """只共享测试数组，检查原生 API 不会修改调用方输入。"""
    assert o3d.__version__ == "0.20.0+amvision.1"
    cloud = o3d.t.geometry.PointCloud(o3d.core.Tensor.from_numpy(points))
    if normals is not None:
        cloud.point.normals = o3d.core.Tensor.from_numpy(normals)
    return cloud


def ellipsoid(dtype):
    """非球形解析曲面，固定随机方向不是拟合器生成的真值。"""
    u = np.random.default_rng(42).normal(size=(256, 3))
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    scale = np.array([3, 5, 8])
    points = u * scale
    normals = points / scale**2
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    return points.astype(dtype), normals.astype(dtype)


@pytest.mark.parametrize("method", ["point-to-point", "point-to-plane"])
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_native_rigid_truth_and_inputs_unchanged(method, dtype):
    """有小量显式初值误差；验证完整旋转/平移、对应、停止和只读输入。"""
    points, normals = ellipsoid(dtype)
    rotation = Rotation.from_euler("xyz", [2, -1, 3], degrees=True).as_matrix()
    translation = np.array([0.1, -0.12, 0.08])
    source = np.asarray((points - translation) @ rotation, dtype=dtype)
    saved = source.copy()
    expected = np.eye(4)
    expected[:3, :3], expected[:3, 3] = rotation, translation
    reg = o3d.t.pipelines.registration
    estimation = (
        reg.TransformationEstimationPointToPoint()
        if method == "point-to-point"
        else reg.TransformationEstimationPointToPlane()
    )
    callbacks = []
    result = reg.icp(
        native_cloud(source.astype(np.float64)),
        native_cloud(points.astype(np.float64), normals.astype(np.float64)),
        0.8,
        o3d.core.Tensor(np.eye(4)),
        estimation,
        reg.ICPConvergenceCriteria(1e-10, 1e-10, 100),
        -1,
        lambda values: callbacks.append(int(values["iteration_index"].item())),
    )
    np.testing.assert_allclose(result.transformation.numpy(), expected, atol=2e-6)
    np.testing.assert_array_equal(source, saved)
    assert callbacks == list(range(len(callbacks)))
    assert result.num_iterations == len(callbacks) and result.fitness == 1
    assert result.inlier_rmse < 1e-5


def test_no_correspondences_returns_zero_rmse_identity_not_a_valid_solution():
    """上游无对应时返回零残差和恒等阵，平台必须根据对应数判无效。"""
    points, _ = ellipsoid(np.float64)
    result = o3d.t.pipelines.registration.icp(
        native_cloud(points + 100), native_cloud(points), 0.1
    )
    assert result.fitness == 0 and result.inlier_rmse == 0
    assert not result.converged and result.num_iterations == 0
    assert (result.correspondence_set.numpy() == -1).all()
    np.testing.assert_array_equal(result.transformation.numpy(), np.eye(4))


def test_callback_cancellation_propagates():
    """取消必须离开原生调用，不能被转换成成功的空结果。"""
    points, _ = ellipsoid(np.float64)

    def cancel(_):
        raise InterruptedError("registration-cancelled")

    with pytest.raises(InterruptedError, match="registration-cancelled"):
        o3d.t.pipelines.registration.icp(
            native_cloud(points),
            native_cloud(points),
            0.1,
            callback_after_iteration=cancel,
        )


def test_fitness_denominator_is_source_not_reference_count():
    """以源码与实测确定覆盖率分母，不能照搬头文件中 target 的描述。"""
    points, _ = ellipsoid(np.float64)
    result = o3d.t.pipelines.registration.evaluate_registration(
        native_cloud(points[:64]), native_cloud(points), 1e-4
    )
    assert result.fitness == 1 and result.correspondence_set.num_elements() == 64


def test_iteration_limit_is_not_convergence():
    """达到迭代上限与满足停止条件需要分开记录。"""
    points, _ = ellipsoid(np.float64)
    result = o3d.t.pipelines.registration.icp(
        native_cloud(points + 0.01),
        native_cloud(points),
        0.1,
        criteria=o3d.t.pipelines.registration.ICPConvergenceCriteria(0, 0, 1),
    )
    assert not result.converged and result.num_iterations == 1
