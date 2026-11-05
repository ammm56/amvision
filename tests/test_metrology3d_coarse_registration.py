"""粗定位真值、候选歧义、来源、存读及失败资源回归。"""

from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.spatial.transform import Rotation

from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.point_cloud_runtime import CloudLocalSource
from backend.contracts.workflows.registration3d import (
    CoarseRegistrationSettings,
    RegistrationMethod,
)
from backend.contracts.workflows.registration3d_search import (
    RegistrationCandidate,
    RegistrationSearchEvidence,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.register_cloud import register_cloud
from custom_nodes.metrology3d_nodes.shared.coarse_registration import (
    coarse_register_arrays,
    working_bytes,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud
from tests.point_cloud_support import policy, create_resource_service
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_registration import settings as local_settings, ASSET_POLICY
from tests.test_metrology3d_pose_operations import operation
from tests.test_point_cloud_runtime import own


def settings(**changes):
    """解析真值使用显式工程值，不作为客户默认或替换原工件阈值。"""
    values = local_settings().model_dump(
        mode="json",
        exclude={"initial_translation", "initial_rotation_degrees", "initialization"},
    )
    values["quality_policy"]["rules"].append(
        dict(item_id="candidate_consistency", unit="1", lower=1)
    )
    return CoarseRegistrationSettings(
        **(
            values
            | dict(
                search=dict(
                    feature_radius=2.0,
                    feature_max_neighbors=40,
                    max_correspondence_distance=0.2,
                    edge_length_ratio=0.9,
                    samples=3,
                    iterations_per_trial=128,
                    trials=3,
                    equivalent_translation=1e-4,
                    equivalent_rotation_degrees=0.01,
                ),
            )
            | changes
        )
    )


def geometry(dtype=np.float64):
    """非均匀椭球采样，解析法向；变换不传入粗定位参数。"""
    directions = np.random.default_rng(28).normal(size=(256, 3))
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    points = directions * [2, 3, 5]
    normals = directions / [2, 3, 5]
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    rotation = Rotation.from_euler("xyz", [37, -22, 81], degrees=True).as_matrix()
    translation = np.array([5, -8, 11])
    source = (points - translation) @ rotation
    return (
        source.astype(dtype),
        points.astype(dtype),
        (normals @ rotation).astype(dtype),
        normals.astype(dtype),
        rotation,
        translation,
    )


@pytest.fixture(params=[np.float32, np.float64])
def scene(request):
    """使用真实 Scope，两云分别建立观察身份，保留大整数和原始行号。"""
    source, reference, sn, rn, rotation, translation = geometry(request.param)
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=source,
        attributes=(
            ("normals", sn, "1"),
            ("label", np.arange(len(source), dtype="u8") + 2**53 + 1, "1"),
        ),
        runtime_policy=policy(
            max_working_bytes=16 * 1024**2,
            max_live_array_bytes=1024**2,
            max_decoded_bytes=1024**2,
            chunk_rows=31,
            chunk_bytes=4096,
        ),
    )
    reference_cloud = runtime.register_source(
        owner=own(
            runtime,
            dict(
                positions=reference,
                normals=rn,
                label=(np.arange(len(source), dtype="u8") + 2**53 + 1)[:, None],
            ),
        ),
        point_count=len(source),
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
    try:
        yield runtime, cloud, reference_cloud, rotation, translation
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("algorithm", ["point-to-point", "point-to-plane"])
def test_unknown_initial_pose_truth_and_persistent_consumers(
    scene, algorithm, tmp_path
):
    runtime, source, reference, rotation, translation = scene
    used = runtime.budget.used
    pose = register_cloud(
        runtime, source, reference, settings(algorithm=algorithm), cancel=lambda: None
    )
    assert pose.state == "found", pose.reason
    assert runtime.budget.used == used
    expected = np.eye(4)
    expected[:3, :3], expected[:3, 3] = rotation, translation
    np.testing.assert_allclose(pose.transform.matrix, expected, atol=3e-6, rtol=0)
    assert (
        pose.method.scope == "feature-se3" and len(pose.method.search.candidates) == 3
    )
    assert all(c.quality.usable for c in pose.method.search.candidates)
    assert Pose3d.model_validate_json(pose.model_dump_json()) == pose
    inverse = operation(runtime, pose)
    identity = operation(runtime, pose, inverse, name="identity")
    np.testing.assert_allclose(identity.transform.matrix, np.eye(4), atol=1e-12)
    transformed = transform_cloud(runtime, source, pose, cancel=lambda: None)
    restored = transform_cloud(runtime, transformed, inverse, cancel=lambda: None)
    with runtime.borrow(source) as a, runtime.borrow(restored) as b:
        for start in range(0, 256, 31):
            stop = min(start + 31, 256)
            np.testing.assert_array_equal(
                a.source_indices(start, stop), b.source_indices(start, stop)
            )
            np.testing.assert_array_equal(
                a.chunk(start, stop)["label"], b.chunk(start, stop)["label"]
            )
            np.testing.assert_allclose(
                a.chunk(start, stop)["positions"],
                b.chunk(start, stop)["positions"],
                atol=3e-6,
                rtol=0,
            )
    service = create_resource_service(tmp_path)
    asset = save_cloud(
        runtime,
        transformed,
        service=service,
        project_id="test",
        name="coarse",
        mode="derived",
        write_identity="c" * 64,
        policy=replace(ASSET_POLICY, max_asset_bytes=4 * 1024**2),
        cancel=lambda: None,
    )
    content = service.read(asset, project_id="test").content.point_cloud
    assert content.provenance.method.parameters.transform == pose.transform
    reloaded = read_asset(
        runtime,
        asset,
        service=service,
        project_id="test",
        policy=replace(ASSET_POLICY, max_asset_bytes=4 * 1024**2),
        cancel=lambda: None,
    )
    with runtime.borrow(reloaded) as a, runtime.borrow(transformed) as b:
        for start in range(0, 256, 31):
            stop = min(start + 31, 256)
            np.testing.assert_array_equal(
                a.chunk(start, stop)["positions"], b.chunk(start, stop)["positions"]
            )


def test_search_settings_reject_hidden_fallback_and_invalid_costs():
    p = settings()
    for change in (
        {"trials": 1},
        {"samples": 2},
        {"iterations_per_trial": 0},
        {"feature_max_neighbors": 2},
        {"equivalent_rotation_degrees": 181},
        {"edge_length_ratio": 1.1},
        {"confidence": 0.99},
        {"voxel_size": 1},
    ):
        with pytest.raises(ValidationError):
            settings(search=p.search.model_dump() | change)
    with pytest.raises(ValidationError):
        settings(quality_policy=local_settings().quality_policy)
    q = p.quality_policy.model_dump(mode="json")
    q["rules"][-1]["include_lower"] = False
    with pytest.raises(ValidationError, match="candidate_consistency"):
        settings(quality_policy=q)


def test_coarse_budget_and_cancel_before_native_work():
    source, target, sn, rn, _, _ = geometry()
    p = settings()
    needed = working_bytes(256, 256, 32, p.search)
    with pytest.raises(InvalidRequestError, match="预算"):
        coarse_register_arrays(
            source,
            target,
            sn,
            rn,
            p,
            observation_id="test",
            max_working_bytes=needed - 1,
            chunk_rows=32,
            cancel=lambda: None,
        )

    def stop():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        coarse_register_arrays(
            source,
            target,
            sn,
            rn,
            p,
            observation_id="test",
            max_working_bytes=needed,
            chunk_rows=32,
            cancel=stop,
        )


def test_persistent_candidate_conflicts_are_not_silently_ranked(scene):
    runtime, source, reference, _, _ = scene
    pose = register_cloud(runtime, source, reference, settings(), cancel=lambda: None)
    assert pose.state == "found"
    original = pose.method.search
    first = original.candidates[0]
    shifted = np.asarray(first.refined_matrix).copy()
    shifted[0, 3] += 1
    other = RegistrationCandidate.model_validate(
        first.model_dump() | dict(trial=1, refined_matrix=shifted.tolist())
    )
    evidence = original.model_copy(
        update={"candidates": (first, other, original.candidates[2])}
    )
    chosen, reason = evidence.select(settings().search)
    assert chosen is None and reason == "ambiguous_candidates"
    # 不能篡改搜索证据后继续读取原 found 位姿或执行其矩阵。
    changed = pose.model_dump()
    changed["method"]["search"] = evidence.model_dump()
    with pytest.raises(ValidationError):
        Pose3d.model_validate(changed)
    with pytest.raises(ValidationError):
        RegistrationMethod.model_validate(
            pose.method.model_dump()
            | dict(
                search=original.model_dump()
                | dict(candidates=original.model_dump()["candidates"][:1])
            )
        )


def test_all_pair_consistency_rejects_single_link_chaining(scene):
    runtime, source, reference, _, _ = scene
    pose = register_cloud(runtime, source, reference, settings(), cancel=lambda: None)
    first = pose.method.search.candidates[0]
    candidates = []
    for i in range(3):
        matrix = np.asarray(first.refined_matrix).copy()
        matrix[0, 3] += i * 0.75
        candidates.append(
            RegistrationCandidate.model_validate(
                first.model_dump() | dict(trial=i, refined_matrix=matrix.tolist())
            )
        )
    evidence = RegistrationSearchEvidence(
        feature_correspondence_count=256, candidates=tuple(candidates)
    )
    assert (
        evidence.select(
            settings().search.model_copy(update={"equivalent_translation": 1})
        )[1]
        == "ambiguous_candidates"
    )


def test_no_candidate_and_cancel_leave_scope_unchanged(scene, monkeypatch):
    """原生返回空候选必须为无效；已分配工作数组后的异常同样释放。"""
    import open3d as o3d

    runtime, source, reference, _, _ = scene
    before = runtime.budget.used

    def no_candidate(*args, **kwargs):
        return o3d.pipelines.registration.RegistrationResult()

    monkeypatch.setattr(
        o3d.pipelines.registration,
        "registration_ransac_based_on_correspondence",
        no_candidate,
    )
    pose = register_cloud(runtime, source, reference, settings(), cancel=lambda: None)
    assert pose.state == "insufficient_quality" and pose.transform is None
    assert len(pose.method.search.candidates) == 3
    assert all(c.initial_matrix is None for c in pose.method.search.candidates)
    assert Pose3d.model_validate_json(pose.model_dump_json()) == pose
    assert runtime.budget.used == before

    def cancelled(*args, **kwargs):
        raise RuntimeError("cancelled during native search")

    monkeypatch.setattr(
        o3d.pipelines.registration,
        "registration_ransac_based_on_correspondence",
        cancelled,
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        register_cloud(runtime, source, reference, settings(), cancel=lambda: None)
    assert runtime.budget.used == before


def test_actual_quality_rejection_and_expired_reference(scene):
    runtime, source, reference, _, _ = scene
    p = settings()
    q = p.quality_policy.model_dump(mode="json")
    next(r for r in q["rules"] if r["item_id"] == "correspondence_count")["lower"] = 257
    pose = register_cloud(
        runtime, source, reference, settings(quality_policy=q), cancel=lambda: None
    )
    assert pose.state == "insufficient_quality" and pose.transform is None
    assert all(not c.quality.usable for c in pose.method.search.candidates)
    with pytest.raises(InvalidRequestError, match="运行"):
        register_cloud(
            runtime,
            source,
            reference.model_copy(update={"run_id": "old-run"}),
            p,
            cancel=lambda: None,
        )


def test_insufficient_mutual_matches_do_not_fall_back():
    """实际常量 FPFH 只留下一个双向对应，不暗中转单向再求解。"""
    p = settings()
    points = np.zeros((8, 3))
    normals = np.tile([0.0, 0.0, 1.0], (8, 1))
    matrix, metrics, reason, evidence = coarse_register_arrays(
        points,
        points.copy(),
        normals,
        normals.copy(),
        p,
        observation_id="test",
        max_working_bytes=1024**2,
        chunk_rows=4,
        cancel=lambda: None,
    )
    assert matrix is None and reason == "insufficient_feature_matches"
    assert evidence.feature_correspondence_count == 1 and not evidence.candidates
    assert metrics["candidate_consistency"] == 0


@pytest.mark.parametrize("bad", [None, np.zeros((256, 3)), np.full((256, 3), np.nan)])
def test_source_normals_are_not_silently_generated(bad):
    source, target, _, normals, _, _ = geometry()
    with pytest.raises(InvalidRequestError, match="法向"):
        coarse_register_arrays(
            source,
            target,
            bad,
            normals,
            settings(),
            observation_id="test",
            max_working_bytes=16 * 1024**2,
            chunk_rows=32,
            cancel=lambda: None,
        )


def test_occluded_reference_is_not_made_valid_by_coarse_search():
    """遮挡不能绕过原双向覆盖与全候选质量；不自动缩小移动云。"""
    source, target, sn, rn, _, _ = geometry()
    matrix, _, reason, evidence = coarse_register_arrays(
        source,
        target[:128].copy(),
        sn,
        rn[:128].copy(),
        settings(),
        observation_id="test",
        max_working_bytes=16 * 1024**2,
        chunk_rows=32,
        cancel=lambda: None,
    )
    assert matrix is None and reason in {
        "no_acceptable_candidate",
        "insufficient_feature_matches",
    }
    assert all(not candidate.quality.usable for candidate in evidence.candidates)


def test_true_symmetric_candidates_are_ambiguous_after_real_icp(monkeypatch):
    """受控提供两个真实对称候选；精化/残差/质量仍由实际原生算法求得。"""
    import open3d as o3d

    rng = np.random.default_rng(36)
    half = rng.normal(size=(128, 3)) * [2, 3, 5]
    points = np.concatenate((half, half * [-1, -1, 1]))
    normals = points / np.linalg.norm(points, axis=1)[:, None]
    native = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    matrices = [np.eye(4), np.diag([-1.0, -1.0, 1.0, 1.0]), np.eye(4)]
    results = iter(
        o3d.pipelines.registration.evaluate_registration(native, native, 0.01, matrix)
        for matrix in matrices
    )
    monkeypatch.setattr(
        o3d.pipelines.registration,
        "registration_ransac_based_on_correspondence",
        lambda *a, **k: next(results),
    )
    matrix, metrics, reason, evidence = coarse_register_arrays(
        points,
        points.copy(),
        normals,
        normals.copy(),
        settings(),
        observation_id="test",
        max_working_bytes=16 * 1024**2,
        chunk_rows=32,
        cancel=lambda: None,
    )
    assert matrix is None and reason == "ambiguous_candidates"
    assert metrics["candidate_consistency"] == 0
    assert all(c.quality.usable for c in evidence.candidates)
    assert all(
        next(m.value for m in c.quality.metrics.items if m.item_id == "rms") < 1e-12
        for c in evidence.candidates
    )
