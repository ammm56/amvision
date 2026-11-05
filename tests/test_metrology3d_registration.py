"""局部配准独立几何、错线、质量、生命周期和持久来源回归。"""

import numpy as np
from dataclasses import replace
import pytest
from pydantic import ValidationError
from scipy.spatial.transform import Rotation

from backend.contracts.workflows.registration3d import RegistrationSettings
from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.measurement3d_query import (
    QueryPoseEvidence,
    pose_query_line,
)
from backend.contracts.workflows.point_cloud_runtime import CloudLocalSource
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.register_cloud import register_cloud
from custom_nodes.metrology3d_nodes.shared.registration import register_arrays
from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.integration.metrology3d.test_registration_native import ellipsoid
from tests.point_cloud_support import policy, create_resource_service
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_pose_operations import (
    operation,
    ASSET_POLICY as SMALL_ASSET_POLICY,
)
from tests.test_point_cloud_runtime import own

ASSET_POLICY = replace(SMALL_ASSET_POLICY, max_asset_bytes=1024**2)


def settings(**changes):
    """显式测试条件，绝不写为生产默认值。"""
    return RegistrationSettings(
        **(
            dict(
                pose_id="aligned",
                source_frame_id="fixture",
                target_frame_id="reference",
                length_unit="mm",
                algorithm="point-to-point",
                initial_translation=[0, 0, 0],
                initial_rotation_degrees=[0, 0, 0],
                max_correspondence_distance=0.8,
                max_iterations=100,
                fitness_change=1e-9,
                rmse_change=1e-9,
                quality_policy=dict(
                    policy_id="test",
                    policy_version=1,
                    rules=[
                        dict(item_id=n, unit="1", lower=v)
                        for n, v in dict(
                            correspondence_count=30,
                            source_coverage=0.95,
                            reference_coverage=0.95,
                            observability=1e-5,
                            rank=6,
                            converged=1,
                        ).items()
                    ]
                    + [
                        dict(item_id="rms", unit="mm", upper=1e-5),
                        dict(item_id="max_residual", unit="mm", upper=1e-4),
                    ],
                ),
            )
            | changes
        )
    )


@pytest.fixture(params=[np.float32, np.float64])
def scene(request):
    """双观测、双坐标；原始行号和大整数属性保持。"""
    points, normals = ellipsoid(request.param)
    rotation = Rotation.from_euler("xyz", [2, -1, 3], degrees=True).as_matrix()
    translation = np.array([0.1, -0.12, 0.08])
    source = np.asarray((points - translation) @ rotation, dtype=request.param)
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=source,
        attributes=(
            ("normals", normals, "1"),
            ("label", np.arange(len(points), dtype="u8") + 2**53 + 1, "1"),
        ),
        runtime_policy=policy(
            max_working_bytes=8 * 1024**2,
            max_live_array_bytes=1024**2,
            max_decoded_bytes=1024**2,
            chunk_rows=31,
            chunk_bytes=4096,
        ),
    )
    reference = runtime.register_source(
        owner=own(
            runtime,
            dict(
                positions=points,
                normals=normals,
                label=(np.arange(len(points), dtype="u8") + 2**53 + 1)[:, None],
            ),
        ),
        point_count=len(points),
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
    assert cloud.observation_id != reference.observation_id
    try:
        yield runtime, cloud, reference, rotation, translation
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("algorithm", ["point-to-point", "point-to-plane"])
def test_truth_fields_pose_inverse_and_save_read(scene, algorithm, tmp_path):
    runtime, cloud, reference, rotation, translation = scene
    before = runtime.budget.used
    pose = register_cloud(
        runtime, cloud, reference, settings(algorithm=algorithm), cancel=lambda: None
    )
    assert pose.state == "found" and runtime.budget.used == before
    expected = np.eye(4)
    expected[:3, :3], expected[:3, 3] = rotation, translation
    np.testing.assert_allclose(pose.transform.matrix, expected, atol=2e-6)
    assert Pose3d.model_validate_json(pose.model_dump_json()) == pose
    inverse = operation(runtime, pose)
    identity = operation(runtime, pose, inverse, name="round-trip")
    np.testing.assert_allclose(identity.transform.matrix, np.eye(4), atol=2e-12)
    assert identity.support == (*pose.support, *pose.support)
    assert len(identity.quality.metrics.items) == 22
    assert Pose3d.model_validate_json(identity.model_dump_json()) == identity
    query_evidence = QueryPoseEvidence.model_validate(
        pose.model_dump(include=set(QueryPoseEvidence.model_fields))
    )
    assert (
        QueryPoseEvidence.model_validate_json(query_evidence.model_dump_json())
        == query_evidence
    )
    line = pose_query_line(pose.transform, (1, 2))
    np.testing.assert_allclose(
        line.query_position, (np.array([1, 2, 0]) - translation) @ rotation, atol=2e-6
    )
    np.testing.assert_allclose(line.direction, rotation[2], atol=2e-6)
    result = transform_cloud(runtime, cloud, pose, cancel=lambda: None)
    restored = transform_cloud(runtime, result, inverse, cancel=lambda: None)
    with runtime.borrow(cloud) as a, runtime.borrow(restored) as b:
        for start in range(0, 256, 31):
            stop = min(start + 31, 256)
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
        result,
        service=service,
        project_id="test",
        name="registration",
        mode="derived",
        write_identity="a" * 64,
        policy=ASSET_POLICY,
        cancel=lambda: None,
    )
    stored = service.read(asset, project_id="test").content.point_cloud
    assert stored.provenance.method.parameters.transform == pose.transform
    reloaded = read_asset(
        runtime,
        asset,
        service=service,
        project_id="test",
        policy=ASSET_POLICY,
        cancel=lambda: None,
    )
    with runtime.borrow(result) as a, runtime.borrow(reloaded) as b:
        for start in range(0, 256, 31):
            stop = min(start + 31, 256)
            np.testing.assert_array_equal(
                a.chunk(start, stop)["positions"], b.chunk(start, stop)["positions"]
            )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"initial_translation": [100, 100, 100]}, "no_overlap"),
        ({"max_iterations": 1}, "iteration_limit"),
    ],
)
def test_no_usable_matrix_on_failure(scene, change, reason):
    runtime, cloud, reference, _, _ = scene
    pose = register_cloud(
        runtime, cloud, reference, settings(**change), cancel=lambda: None
    )
    assert pose.reason == reason and pose.transform is None and not pose.quality.usable
    assert operation(runtime, pose).transform is None


def test_planar_point_to_plane_degeneracy():
    x, y = np.meshgrid(np.arange(5.0), np.arange(6.0))
    p = np.column_stack((x.ravel(), y.ravel(), np.zeros(x.size)))
    matrix, metrics, reason = register_arrays(
        p,
        p,
        np.tile([0.0, 0.0, 1.0], (len(p), 1)),
        settings(algorithm="point-to-plane"),
        max_working_bytes=1024**2,
        chunk_rows=11,
        cancel=lambda: None,
    )
    assert matrix is None and reason == "degenerate_support" and metrics["rank"] == 3


def test_identity_budget_cancellation_and_stale_rejected(scene):
    runtime, cloud, reference, _, _ = scene
    with pytest.raises(InvalidRequestError, match="坐标"):
        register_cloud(runtime, reference, cloud, settings(), cancel=lambda: None)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 12:
            raise InterruptedError("cancel")

    before = runtime.budget.used
    with pytest.raises(InterruptedError):
        register_cloud(runtime, cloud, reference, settings(), cancel=cancel)
    assert runtime.budget.used == before
    p, _ = ellipsoid(np.float64)
    with pytest.raises(InvalidRequestError, match="预算"):
        register_arrays(
            p,
            p,
            None,
            settings(),
            max_working_bytes=1,
            chunk_rows=31,
            cancel=lambda: None,
        )


def test_contract_required_quality_and_tampering(scene):
    runtime, cloud, reference, _, _ = scene
    with pytest.raises(ValidationError):
        settings(target_frame_id="fixture")
    policy = settings().quality_policy.model_dump()
    policy["rules"] = policy["rules"][1:]
    with pytest.raises(ValidationError, match="correspondence_count"):
        settings(quality_policy=policy)
    pose = register_cloud(runtime, cloud, reference, settings(), cancel=lambda: None)
    raw = pose.model_dump(mode="json")
    raw["support"][1]["observation_id"] = cloud.observation_id
    with pytest.raises(ValidationError, match="位姿支持"):
        Pose3d.model_validate(raw)


def test_explicit_initial_rotation_convention():
    p = settings(initial_rotation_degrees=[30, 20, 10], initial_translation=[1, 2, 3])
    expected = Rotation.from_euler("xyz", [30, 20, 10], degrees=True).as_matrix()
    np.testing.assert_allclose(
        np.asarray(p.initial_matrix())[:3, :3], expected, atol=1e-15
    )


@pytest.mark.parametrize("bad", ["missing", "zero", "nan"])
def test_bad_reference_normals_are_input_errors(bad):
    """坏法向不能被静默丢点、自动拟合或变成匹配失败。"""
    p, n = ellipsoid(np.float64)
    if bad == "missing":
        n = None
    else:
        n[0] = 0 if bad == "zero" else np.nan
    with pytest.raises(InvalidRequestError, match="法向"):
        register_arrays(
            p,
            p,
            n,
            settings(algorithm="point-to-plane"),
            max_working_bytes=1024**2,
            chunk_rows=31,
            cancel=lambda: None,
        )


def test_unavailable_quality_failure_and_stale_support(scene):
    """缺测、严格质量拒绝与过期权限分别处理，不复用成功矩阵。"""
    runtime, cloud, reference, _, _ = scene
    absent = register_cloud(
        runtime,
        cloud.unavailable("missing_input"),
        reference,
        settings(),
        cancel=lambda: None,
    )
    assert absent.reason == "upstream_unavailable" and absent.transform is None
    policy = settings().quality_policy.model_dump()
    for r in policy["rules"]:
        if r["item_id"] == "correspondence_count":
            r["lower"] = 1000
    result = register_cloud(
        runtime, cloud, reference, settings(quality_policy=policy), cancel=lambda: None
    )
    assert result.reason == "quality_failed" and result.transform is None
    pose = register_cloud(runtime, cloud, reference, settings(), cancel=lambda: None)
    changed = pose.model_copy(update={"run_id": "old"})
    with pytest.raises(InvalidRequestError, match="位姿运行"):
        transform_cloud(runtime, cloud, changed, cancel=lambda: None)


def test_coverage_directions_and_residuals_use_complete_correspondences():
    """参考覆盖分母与源覆盖分开；未覆盖区域没有被隐藏。"""
    p, _ = ellipsoid(np.float64)
    _, metrics, _ = register_arrays(
        p[:64],
        p,
        None,
        settings(max_correspondence_distance=1e-4),
        max_working_bytes=1024**2,
        chunk_rows=31,
        cancel=lambda: None,
    )
    assert metrics["correspondence_count"] == 64
    assert metrics["source_coverage"] == 1 and metrics["reference_coverage"] == 0.25
    assert metrics["rms"] < 1e-10


def test_numeric_span_is_rejected_before_native_index():
    p, _ = ellipsoid(np.float64)
    p[0, 0] = 1e200
    with pytest.raises(InvalidRequestError, match="数值范围"):
        register_arrays(
            p,
            p,
            None,
            settings(),
            max_working_bytes=1024**2,
            chunk_rows=31,
            cancel=lambda: None,
        )
