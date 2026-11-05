"""台面约束独立三维真值、来源、保存与取消；不使用被测求解器造期望值。"""

from dataclasses import replace
import numpy as np
import pytest
from pydantic import ValidationError
from scipy.spatial.transform import Rotation

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.point_cloud_runtime import CloudLocalSource
from backend.contracts.workflows.registration3d import DatumRegistrationSettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.register_cloud import register_cloud
from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.integration.metrology3d.test_registration_native import ellipsoid
from tests.test_metrology3d_registration import settings as local_settings, ASSET_POLICY
from tests.test_metrology3d_pose_operations import operation
from tests.test_metrology3d_frame import frame_parameters
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_runtime import own
from tests.point_cloud_support import policy, create_resource_service


def settings(**changes):
    """测试用配方，秩三对应三个自由度，其他原质量门槛不降低。"""
    p = local_settings().model_dump(mode="json")
    for k in ("initial_translation", "initial_rotation_degrees"):
        del p[k]
    p.update(
        initialization="datum",
        initial_uv=[0, 0],
        initial_angle_degrees=0,
        max_solver_evaluations=40,
        solver_tolerance=1e-11,
    )
    for r in p["quality_policy"]["rules"]:
        if r["item_id"] == "rank":
            r["lower"] = 3
    p["quality_policy"]["rules"].append(dict(item_id="datum_valid", unit="1", lower=1))
    return DatumRegistrationSettings(**(p | changes))


def datum(runtime, cloud, rotation, origin, name):
    """显式 ROI → Fit Plane → Build Frame，所有来源都来自当前原云。"""
    support, _ = crop_roi(
        runtime,
        cloud,
        CropCloudParameters(
            roi_id=name,
            rois=[
                dict(
                    roi_id=name,
                    frame_id=cloud.spatial.frame_id,
                    length_unit="mm",
                    kind="box",
                    geometry=dict(
                        center=origin, size=[40, 40, 0.02], rotation=rotation.tolist()
                    ),
                )
            ],
        ),
        cancel=lambda: None,
    )
    plane = fit_plane(
        runtime,
        support,
        plane_parameters(
            feature_id="primary",
            positive_normal=rotation[:, 2].tolist(),
        ),
        cancel=lambda: None,
    )
    result = build_frame(
        runtime,
        [plane],
        frame_parameters(
            pose_id=name,
            target_frame_id=name,
            positive_z=rotation[:, 2].tolist(),
            origin=dict(kind="anchor-projection", anchor=origin),
            x_axis=dict(kind="direction", direction=rotation[:, 0].tolist()),
        ),
        cancel=lambda: None,
    )
    assert result.state == "found"
    return result


@pytest.fixture(params=[np.float32, np.float64])
def scene(request):
    """两个不同倾斜扫描坐标；只有基准内实际运动为三自由度。"""
    p, normals = ellipsoid(np.float64)
    points = np.vstack(
        ([[-10, -10, 0], [10, -10, 0], [-10, 10, 0], [10, 10, 0]], p + [0, 0, 12])
    )
    normals = np.vstack((np.tile([0, 0, 1], (4, 1)), normals))
    rs = Rotation.from_euler("xyz", [17, -13, 9], degrees=True).as_matrix()
    rr = Rotation.from_euler("xyz", [-21, 8, 31], degrees=True).as_matrix()
    rz = Rotation.from_euler("z", 3, degrees=True).as_matrix()
    a, b, shift = np.array([3, 5, 7]), np.array([-6, 2, 4]), np.array([0.1, -0.12, 0])
    source = (points @ rs.T + a).astype(request.param)
    reference = ((points @ rz.T + shift) @ rr.T + b).astype(request.param)
    labels = np.arange(len(p) + 4, dtype="u8") + 2**53 + 1
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=source,
        attributes=(
            ("normals", (normals @ rs.T).astype(request.param), "1"),
            ("label", labels, "1"),
        ),
        runtime_policy=policy(
            max_working_bytes=8 * 1024**2,
            max_live_array_bytes=2 * 1024**2,
            max_decoded_bytes=2 * 1024**2,
            chunk_rows=31,
            chunk_bytes=4096,
        ),
    )
    target = runtime.register_source(
        owner=own(
            runtime,
            dict(
                positions=reference,
                normals=(normals @ rz.T @ rr.T).astype(request.param),
                label=labels[:, None],
            ),
        ),
        point_count=len(reference),
        fields=cloud.fields,
        spatial=cloud.spatial.model_copy(update={"frame_id": "reference"}),
        source=CloudLocalSource(
            kind="local-array",
            content_sha256="3" * 64,
            descriptor_sha256="4" * 64,
            source_observation_id=None,
        ),
        source_metadata=None,
        cancel=lambda: None,
    )
    first, second = (
        datum(runtime, cloud, rs, a.tolist(), "source-table"),
        datum(runtime, target, rr, b.tolist(), "reference-table"),
    )
    expected = np.eye(4)
    expected[:3, :3] = rr @ rz @ rs.T
    expected[:3, 3] = b + rr @ shift - expected[:3, :3] @ a
    try:
        yield runtime, cloud, target, first, second, expected
    finally:
        assert not scope.close() and runtime.budget.used == 0


def run(scene, **changes):
    """统一调用既有节点函数，不绕过运行身份校验。"""
    runtime, cloud, reference, first, second, _ = scene
    return register_cloud(
        runtime,
        cloud,
        reference,
        settings(**changes),
        source_datum=first,
        reference_datum=second,
        cancel=lambda: None,
    )


@pytest.mark.parametrize("algorithm", ["point-to-point", "point-to-plane"])
def test_independent_tilted_frames_truth_save_inverse_fields(
    scene, algorithm, tmp_path
):
    runtime, cloud, _, _, _, expected = scene
    before = runtime.budget.used
    pose = run(scene, algorithm=algorithm)
    assert pose.state == "found" and runtime.budget.used == before
    np.testing.assert_allclose(pose.transform.matrix, expected, atol=2e-6)
    assert len(pose.support) == 4 and pose.method.scope == "datum-se2"
    assert pose.method.datum.correction[2] == (0, 0, 1, 0)
    assert Pose3d.model_validate_json(pose.model_dump_json()) == pose
    inverse = operation(runtime, pose)
    identity = operation(runtime, pose, inverse)
    np.testing.assert_allclose(identity.transform.matrix, np.eye(4), atol=1e-12)
    moved = transform_cloud(runtime, cloud, pose, cancel=lambda: None)
    restored = transform_cloud(runtime, moved, inverse, cancel=lambda: None)
    with runtime.borrow(cloud) as a, runtime.borrow(restored) as b:
        for start in range(0, cloud.point_count, 31):
            stop = min(start + 31, cloud.point_count)
            np.testing.assert_array_equal(
                a.source_indices(start, stop), b.source_indices(start, stop)
            )
            x, y = a.chunk(start, stop), b.chunk(start, stop)
            np.testing.assert_array_equal(x["label"], y["label"])
            np.testing.assert_allclose(x["positions"], y["positions"], atol=2e-6)
            assert x["positions"].dtype == y["positions"].dtype
    service = create_resource_service(tmp_path)
    asset = save_cloud(
        runtime,
        moved,
        service=service,
        project_id="test",
        name="datum",
        mode="derived",
        write_identity="a" * 64,
        policy=replace(ASSET_POLICY, max_asset_bytes=2 * 1024**2),
        cancel=lambda: None,
    )
    stored = service.read(asset, project_id="test").content.point_cloud
    assert stored.provenance.method.parameters.transform == pose.transform
    read_asset(
        runtime,
        asset,
        service=service,
        project_id="test",
        policy=replace(ASSET_POLICY, max_asset_bytes=2 * 1024**2),
        cancel=lambda: None,
    )


def test_contract_and_tamper(scene):
    pose = run(scene)
    for field, value in [
        ("initial_uv", [0, 0, 1]),
        ("solver_tolerance", 0),
        ("max_solver_evaluations", 0),
    ]:
        with pytest.raises(ValidationError):
            settings(**{field: value})
    raw = pose.model_dump(mode="json")
    raw["method"]["datum"]["correction"][2][3] = 0.01
    with pytest.raises(ValidationError, match="台面约束"):
        Pose3d.model_validate(raw)
    raw = pose.model_dump(mode="json")
    raw["support"][2]["observation_id"] = raw["support"][1]["observation_id"]
    with pytest.raises(ValidationError, match="支持身份"):
        Pose3d.model_validate(raw)


def test_bad_sources_budget_cancel_and_failure(scene):
    runtime, cloud, reference, first, second, _ = scene
    for wrong in (None, second, first.model_copy(update={"run_id": "old"})):
        with pytest.raises(InvalidRequestError):
            register_cloud(
                runtime,
                cloud,
                reference,
                settings(),
                source_datum=wrong,
                reference_datum=second,
                cancel=lambda: None,
            )
    for changes, reason in [
        ({"initial_uv": [100, 100]}, "no_overlap"),
        ({"max_solver_evaluations": 1}, "solver_limit"),
    ]:
        failed = run(scene, **changes)
        assert failed.transform is None and failed.reason == reason
        assert operation(runtime, failed).transform is None
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 60:
            raise InterruptedError("test cancellation")

    before = runtime.budget.used
    with pytest.raises(InterruptedError):
        register_cloud(
            runtime,
            cloud,
            reference,
            settings(),
            source_datum=first,
            reference_datum=second,
            cancel=cancel,
        )
    assert runtime.budget.used == before


def test_planar_rank_and_forbidden_height(scene):
    """平面点到面没有面内约束；点到点不能用高度漂移消除残差。"""
    from custom_nodes.metrology3d_nodes.shared.datum_registration import (
        register_datum_arrays,
    )
    from backend.contracts.workflows.frame3d_evidence import FramePoseEvidence

    _, _, _, first, second, _ = scene
    frames = tuple(
        FramePoseEvidence.model_validate(
            f.model_dump(include=set(FramePoseEvidence.model_fields))
        )
        for f in (first, second)
    )
    fs, fr = (np.asarray(f.transform.matrix) for f in frames)
    uv = np.random.default_rng(15).normal(size=(60, 3))
    uv[:, 2] = 0
    src = (uv - fs[:3, 3]) @ fs[:3, :3]
    dst = (uv - fr[:3, 3]) @ fr[:3, :3]
    normal = np.tile(fr[2, :3], (len(uv), 1))
    args = dict(max_working_bytes=1024**2, chunk_rows=17, cancel=lambda: None)
    result, metrics, reason, correction = register_datum_arrays(
        src, dst, normal, settings(algorithm="point-to-plane"), frames, **args
    )
    assert (
        result is correction is None
        and reason == "degenerate_support"
        and metrics["rank"] == 0
    )
    # 真实坐标偏移高度，不修改基准；三自由度解保留全部 Z 残差。
    dst += fr[2, :3] * 0.05
    result, metrics, reason, correction = register_datum_arrays(
        src, dst, None, settings(), frames, **args
    )
    assert reason is None and metrics["rms"] > 0.049
    assert correction[2].tolist() == [0, 0, 1, 0]
    with pytest.raises(InvalidRequestError, match="预算"):
        register_datum_arrays(
            src, dst, None, settings(), frames, **(args | {"max_working_bytes": 1})
        )
    result, _, reason, _ = register_datum_arrays(
        src[:2], dst[:2], None, settings(), frames, **args
    )
    assert result is None and reason == "insufficient_support"


def test_unavailable_datum_and_support_validation(scene):
    """实际失败的 Build Frame 传递无效，不绕过质量或生成空矩阵。"""
    runtime, cloud, reference, first, second, _ = scene
    plane = fit_plane(
        runtime,
        first.support[0],
        plane_parameters(feature_id="primary"),
        cancel=lambda: None,
    )
    q = frame_parameters().quality_policy.model_dump(mode="json")
    q["rules"][0]["lower"] = 1.1
    invalid = build_frame(
        runtime, [plane], frame_parameters(quality_policy=q), cancel=lambda: None
    )
    assert invalid.state != "found"
    pose = register_cloud(
        runtime,
        cloud,
        reference,
        settings(),
        source_datum=invalid,
        reference_datum=second,
        cancel=lambda: None,
    )
    assert pose.transform is None and pose.reason == "upstream_unavailable"
    assert Pose3d.model_validate_json(pose.model_dump_json()) == pose
    assert operation(runtime, pose).transform is None
