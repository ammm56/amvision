"""刚体变换独立真值、字段保真、失败和数组释放。"""

import numpy as np
import pytest

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud
from tests.test_metrology3d_frame import frame_parameters
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud


def transform_source(dtype):
    """解析平面 z=3，目标轴 X=源 Y，Y=-源 X，Z=源 Z。"""
    points = np.array([[1, 2, 3], [2, 2, 3], [1, 3, 3], [2, 3, 3]], dtype=dtype)
    return make_cloud(
        unit="mm",
        coordinates=points,
        attributes=(
            ("normals", np.tile(np.array([1, 0, 0], dtype=dtype), (4, 1)), "1"),
            (
                "colors",
                np.array(
                    [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12]], dtype=np.uint8
                ),
                "1",
            ),
            ("label", np.array([2**64 - 1, 1, 2, 3], dtype=np.uint64), "1"),
        ),
    )


def cloud_pose(runtime, cloud):
    """拟合输入真值，但期望矩阵和坐标由解析式断言。"""
    features = fit_plane(
        runtime, cloud, plane_parameters(feature_id="primary"), cancel=lambda: None
    )
    pose = build_frame(
        runtime,
        [features],
        frame_parameters(x_axis=dict(kind="direction", direction=[0, 1, 0])),
        cancel=lambda: None,
    )
    return features, pose


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_transform_fields_normals_and_source_indices(dtype):
    scope, runtime, cloud = transform_source(dtype)
    _, pose = cloud_pose(runtime, cloud)
    result = transform_cloud(runtime, cloud, pose, cancel=lambda: None)
    assert result.fields == cloud.fields and result.spatial.frame_id == "part"
    with runtime.borrow(result) as view, runtime.borrow(cloud) as source:
        actual = {
            name: np.concatenate([view.chunk(i, i + 2)[name] for i in (0, 2)])
            for name in ("positions", "normals", "label", "colors")
        }
        expected = np.array([[0, 0, 0], [0, -1, 0], [1, 0, 0], [1, -1, 0]])
        np.testing.assert_allclose(actual["positions"], expected, atol=1e-12)
        np.testing.assert_allclose(
            actual["normals"], np.tile([0, -1, 0], (4, 1)), atol=1e-12
        )
        assert actual["positions"].dtype == dtype and actual["normals"].dtype == dtype
        for name in ("label", "colors"):
            np.testing.assert_array_equal(
                actual[name],
                np.concatenate([source.chunk(i, i + 2)[name] for i in (0, 2)]),
            )
        np.testing.assert_array_equal(
            np.concatenate([view.source_indices(i, i + 2) for i in (0, 2)]),
            np.arange(4),
        )
    p = CropCloudParameters(
        roi_id="roi",
        rois=[
            dict(
                roi_id="roi",
                frame_id="part",
                length_unit="mm",
                kind="box",
                geometry=dict(
                    center=[1, -0.5, 0], rotation=np.eye(3).tolist(), size=[0.5, 2, 1]
                ),
            )
        ],
    )
    subset, _ = crop_roi(runtime, result, p, cancel=lambda: None)
    with runtime.borrow(subset) as view:
        np.testing.assert_array_equal(view.source_indices(0, 2), [2, 3])
    assert runtime.source_point_count(subset) == 4
    assert result.provenance.method.parameters.transform == pose.transform
    assert not scope.close() and runtime.budget.used == 0


def test_transform_invalid_pose_no_allocation_and_no_stale_result():
    scope, runtime, cloud = transform_source(np.float32)
    features, pose = cloud_pose(runtime, cloud)
    bad = build_frame(
        runtime,
        [features],
        frame_parameters(x_axis=dict(kind="direction", direction=[0, 0, 1])),
        cancel=lambda: None,
    )
    before = runtime.budget.used
    result = transform_cloud(runtime, cloud, bad, cancel=lambda: None)
    assert (
        result.state == "unavailable"
        and result.cloud_id is None
        and result.spatial.frame_id == "part"
    )
    assert result.reason == "datum_axis_parallel" and runtime.budget.used == before
    assert transform_cloud(runtime, cloud, pose, cancel=lambda: None).state == "ready"
    with pytest.raises(InvalidRequestError, match="不一致"):
        transform_cloud(
            runtime,
            cloud,
            pose.model_copy(update={"observation_id": "other"}),
            cancel=lambda: None,
        )
    with pytest.raises(InvalidRequestError):
        transform_cloud(
            runtime,
            cloud.model_copy(update={"point_count": 3}),
            bad,
            cancel=lambda: None,
        )
    assert not scope.close() and runtime.budget.used == 0


def test_transform_then_inverse_preserves_lengths():
    scope, runtime, cloud = transform_source(np.float64)
    _, pose = cloud_pose(runtime, cloud)
    forward = transform_cloud(runtime, cloud, pose, cancel=lambda: None)
    features = fit_plane(
        runtime, forward, plane_parameters(feature_id="primary"), cancel=lambda: None
    )
    inverse = build_frame(
        runtime,
        [features],
        frame_parameters(
            target_frame_id="restored",
            origin=dict(kind="anchor-projection", anchor=[0, 0, 0]),
            x_axis=dict(kind="direction", direction=[0, -1, 0]),
        ),
        cancel=lambda: None,
    )
    restored = transform_cloud(runtime, forward, inverse, cancel=lambda: None)
    with runtime.borrow(restored) as view:
        actual = np.concatenate([view.chunk(i, i + 2)["positions"] for i in (0, 2)])
    # 逆轴旋转保留相对位移；原点仍为显式锚点，不从输入质心推断平移。
    np.testing.assert_allclose(
        actual, [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], atol=1e-12
    )
    assert np.linalg.norm(actual[-1] - actual[0]) == pytest.approx(np.sqrt(2))
    assert not scope.close()


def test_transform_overflow_fails_and_releases_storage():
    scope, runtime, cloud = transform_source(np.float32)
    features, _ = cloud_pose(runtime, cloud)
    pose = build_frame(
        runtime,
        [features],
        frame_parameters(origin=dict(kind="anchor-projection", anchor=[-1e39, 0, 0])),
        cancel=lambda: None,
    )
    before = runtime.budget.used
    with pytest.raises((FloatingPointError, InvalidRequestError)):
        transform_cloud(runtime, cloud, pose, cancel=lambda: None)
    assert runtime.budget.used == before
    assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("at", range(1, 15))
def test_transform_cancel_releases_every_allocation_boundary(at):
    scope, runtime, cloud = transform_source(np.float64)
    _, pose = cloud_pose(runtime, cloud)
    before = runtime.budget.used
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == at:
            raise RuntimeError("cancelled")

    try:
        transform_cloud(runtime, cloud, pose, cancel=cancel)
    except RuntimeError as error:
        assert str(error) == "cancelled"
        assert runtime.budget.used == before
    assert not scope.close() and runtime.budget.used == 0
