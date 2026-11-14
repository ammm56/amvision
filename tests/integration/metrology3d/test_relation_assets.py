"""关系支持在一个版本中提交，原 Scope 释放后恢复真实父链。"""

from io import BytesIO
from dataclasses import replace

import numpy as np
import pytest

from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
    read_asset_bundle,
    save_cloud,
)
from custom_nodes.metrology3d_nodes.shared.relation_result import relation_evidence
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_dimension_runtime import analytic_edges
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_relations import parameters
from tests.test_point_cloud_assets import POLICY as BASE_POLICY
from tests.test_metrology3d_height_step import two_planes
from backend.service.application.errors import InvalidRequestError

POLICY = replace(BASE_POLICY, chunk_bytes=128, max_archive_bytes=1024 * 1024)


@pytest.mark.parametrize("quality_failure", [False, True])
def test_save_release_import_restore_distinct_supports(
    tmp_path, monkeypatch, quality_failure
):
    """空环境搬运后同源但不混淆 A/B，失败质量和原行号均保留。"""
    limits = policy(max_working_bytes=1024 * 1024)
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[0, -2, 0], [0, 2, 0], [4, -2, 0], [4, 2, 0]], dtype=float
        ),
        runtime_policy=limits,
    )
    service = create_resource_service(tmp_path)
    try:
        features = analytic_edges(runtime, root)
        p = parameters("line-line", support_mode="finite")
        if quality_failure:
            raw = p.model_dump(mode="json")
            raw["quality_policy"]["rules"].append(
                dict(item_id="contacts_unique", unit="1", lower=1)
            )
            p = type(p).model_validate(raw)
        evidence = relation_evidence(runtime, root, [features], p, cancel=lambda: None)
        old_observation = root.observation_id
        asset = save_cloud(
            runtime,
            root,
            features=features,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="relation",
            write_identity="e" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        document = service.read(asset, project_id="test")
        assert len(document.content.point_cloud.relation.steps) == 2
        archive = BytesIO()
        service.export_cloud_archive(
            asset, project_id="test", stream=archive, policy=POLICY, cancel=lambda: None
        )
        destination = create_resource_service(tmp_path / "empty")
        imported = destination.import_cloud_archive(
            stream=archive,
            project_id="test",
            name="restored",
            write_identity="f" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0
    _verify_restored(
        monkeypatch,
        limits,
        imported,
        destination,
        old_observation,
        quality_failure,
        evidence,
    )


def test_plane_branches_restore_failure_rolls_back_only_new_resources(
    tmp_path, monkeypatch
):
    """完整两面保存；第二分支恢复取消后，旧云仍能读取且无新预算残留。"""
    scope, runtime, root, _, _, groups = two_planes(slope=0.25)
    service = create_resource_service(tmp_path)
    p = parameters(
        "plane-angle",
        reference=dict(kind="plane", feature_id="reference"),
        target=dict(kind="plane", feature_id="target"),
    )
    try:
        evidence = relation_evidence(runtime, root, groups, p, cancel=lambda: None)
        asset = save_cloud(
            runtime,
            root,
            features=groups,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="planes",
            write_identity="d" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0
    scope, runtime, previous = make_cloud(
        unit="mm", runtime_policy=policy(max_working_bytes=1024 * 1024)
    )
    before = runtime.budget.used, runtime.storage_scope.resource_count
    original = runtime.register_subset
    count = 0

    def interrupted(**kwargs):
        nonlocal count
        count += 1
        value = original(**kwargs)
        if count == 2:
            raise InterruptedError("test cancellation")
        return value

    try:
        monkeypatch.setattr(runtime, "register_subset", interrupted)
        with pytest.raises(InterruptedError):
            read_asset_bundle(
                runtime,
                asset,
                service=service,
                project_id="test",
                policy=POLICY,
                cancel=lambda: None,
            )
        assert (runtime.budget.used, runtime.storage_scope.resource_count) == before
        with runtime.borrow(previous) as view:
            assert len(view.chunk(0, 1)["positions"]) == 1
        monkeypatch.setattr(runtime, "register_subset", original)
        cloud, features, restored = read_asset_bundle(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert restored.items[0].value == pytest.approx(evidence.items[0].value)
        assert {f.support.observation_id for f in features.items} == {
            cloud.observation_id
        }
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_decode_interruption_has_no_partial_runtime(tmp_path, monkeypatch):
    """故障发生在派生数组解码中，整个恢复事务撤销。"""
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[0, -2, 0], [0, 2, 0], [4, -2, 0], [4, 2, 0]], dtype=float
        ),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    service = create_resource_service(tmp_path)
    try:
        features = analytic_edges(runtime, root)
        evidence = relation_evidence(
            runtime, root, [features], parameters("line-line"), cancel=lambda: None
        )
        asset = save_cloud(
            runtime,
            root,
            features=features,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="line",
            write_identity="c" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        before = runtime.budget.used, runtime.storage_scope.resource_count
        from custom_nodes.metrology3d_nodes.shared import relation_assets

        original = relation_assets._read_step

        def broken(*args, **kwargs):
            original(*args, **kwargs)
            raise InvalidRequestError("corrupt relation")

        monkeypatch.setattr(relation_assets, "_read_step", broken)
        with pytest.raises(InvalidRequestError, match="corrupt"):
            read_asset_bundle(
                runtime,
                asset,
                service=service,
                project_id="test",
                policy=POLICY,
                cancel=lambda: None,
            )
        assert (runtime.budget.used, runtime.storage_scope.resource_count) == before
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("corruption", ["out-of-range", "duplicate", "truncated"])
def test_relation_bytes_reject_invalid_indices_with_matching_digest(
    tmp_path, corruption
):
    """摘要匹配也不能导入越界或重复父索引，按单字节分块覆盖记录边界。"""
    from hashlib import sha256
    from backend.contracts.workflows.point_cloud_assets import CloudBlob
    from backend.service.application.workflows.documents.cloud_resource_blobs import (
        CheckedBlobStream,
        cloud_blob_key,
    )

    scope, runtime, root, _, _, groups = two_planes(slope=0.25)
    service = create_resource_service(tmp_path)
    try:
        features = groups
        evidence = relation_evidence(
            runtime,
            root,
            groups,
            parameters(
                "plane-angle",
                reference=dict(kind="plane", feature_id="reference"),
                target=dict(kind="plane", feature_id="target"),
            ),
            cancel=lambda: None,
        )
        reference = save_cloud(
            runtime,
            root,
            features=features,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="strict",
            write_identity="9" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        asset = service.read(reference, project_id="test").content.point_cloud
        blob = next(b for b in asset.blobs if b.role == "relation")
        with service.storage.open_read_snapshot(
            cloud_blob_key(service, reference, blob)
        ) as snapshot:
            payload = bytearray(snapshot.stream.read())
        first = asset.relation.steps[0].arrays[0]
        dtype = np.dtype(first.dtype).newbyteorder("<")
        if corruption == "out-of-range":
            payload[: dtype.itemsize] = np.array(
                [root.point_count], dtype=dtype
            ).tobytes()
        elif corruption == "duplicate":
            payload[dtype.itemsize : 2 * dtype.itemsize] = payload[: dtype.itemsize]
        else:
            payload = payload[:-1]
        altered = CloudBlob.model_validate(
            {**blob.model_dump(), "sha256": sha256(payload).hexdigest()}
        )
        checked = CheckedBlobStream(BytesIO(payload), altered, lambda: None, asset)
        with pytest.raises(InvalidRequestError):
            while checked.read(1):
                pass
    finally:
        assert not scope.close() and runtime.budget.used == 0


def _verify_restored(
    monkeypatch,
    limits,
    imported,
    destination,
    old_observation,
    quality_failure,
    evidence,
):
    """在原 Scope 完全退出后核对重新登记的支持。"""

    def forbidden(*args, **kwargs):
        raise AssertionError("restore must not fit")

    monkeypatch.setattr("scipy.optimize.least_squares", forbidden)
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="restored-relation", policy=limits)
    try:
        cloud, group, replay = read_asset_bundle(
            runtime,
            imported.reference,
            service=destination,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert cloud.observation_id != old_observation
        assert group.items[0].support != group.items[1].support
        for feature, rows in zip(group.items, ([0, 1], [2, 3])):
            assert feature.support.observation_id == cloud.observation_id
            with runtime.borrow(feature.support) as view:
                assert view.source_indices(0, 2).ravel().tolist() == rows
        assert replay.items[0].value == (None if quality_failure else 4)
        assert replay.items[0].reason == evidence.items[0].reason
        second = save_cloud(
            runtime,
            cloud,
            features=group,
            evidence=replay,
            service=destination,
            project_id="test",
            mode="derived",
            name="second generation",
            write_identity="7" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        next_cloud, next_group, next_evidence = read_asset_bundle(
            runtime,
            second,
            service=destination,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert next_cloud.observation_id != cloud.observation_id
        assert next_evidence.items[0].value == replay.items[0].value
        assert next_evidence.items[0].reason == replay.items[0].reason
        assert len(next_group.items) == 2
        with runtime.borrow(group.items[0].support) as previous:
            assert previous.source_indices(0, 2).ravel().tolist() == [0, 1]
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("kind", ["stride", "voxel-centroid"])
def test_primary_derived_members_and_fields_are_preserved(tmp_path, kind):
    """原始行号视图和体素生成成员均沿原登记接口恢复，不伪造源点。"""
    from tests.test_metrology3d_resample import parameters as resample_parameters
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
    from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters

    scope, runtime, root = make_cloud(
        unit="mm", runtime_policy=policy(max_working_bytes=1024 * 1024)
    )
    service = create_resource_service(tmp_path)
    try:
        raw = resample_parameters(kind).model_dump()
        if kind != "stride":
            raw["settings"]["frame_id"] = root.spatial.frame_id
        cloud, _ = resample_cloud(
            runtime,
            root,
            ResampleCloudParameters.model_validate(raw),
            cancel=lambda: None,
        )
        p = parameters(
            reference=dict(kind="coordinate", position=[0, 0, 0]),
            target=dict(kind="coordinate", position=[3, 4, 0]),
        )
        evidence = relation_evidence(runtime, cloud, [], p, cancel=lambda: None)
        asset = save_cloud(
            runtime,
            cloud,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="derived",
            write_identity="a" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        restored, _, replay = read_asset_bundle(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert replay.items[0].value == 5
        assert restored.vertex_kind == cloud.vertex_kind
        assert (
            restored.fields == cloud.fields
            and restored.point_count == cloud.point_count
        )
        with runtime.borrow(cloud) as a, runtime.borrow(restored) as b:
            for key, values in a.chunk(0, cloud.point_count).items():
                assert values.tobytes() == b.chunk(0, cloud.point_count)[key].tobytes()
            if kind == "stride":
                np.testing.assert_array_equal(
                    a.source_indices(0, cloud.point_count),
                    b.source_indices(0, cloud.point_count),
                )
            else:
                for key, values in a.lineage_chunk(0, cloud.point_count).items():
                    assert (
                        values.tobytes()
                        == b.lineage_chunk(0, cloud.point_count)[key].tobytes()
                    )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_point_only_zero_attachment_and_budget_failure(tmp_path):
    """无派生分支时仍保存证据；恢复预算不足拒绝且无残留。"""
    scope, runtime, root = make_cloud(
        unit="mm", runtime_policy=policy(max_working_bytes=1024 * 1024)
    )
    service = create_resource_service(tmp_path)
    try:
        evidence = relation_evidence(
            runtime, root, [], parameters(), cancel=lambda: None
        )
        asset = save_cloud(
            runtime,
            root,
            evidence=evidence,
            service=service,
            project_id="test",
            mode="derived",
            name="points",
            write_identity="b" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        assert (
            service.read(
                asset, project_id="test"
            ).content.point_cloud.relation.byte_length()
            == 0
        )
        _, _, replay = read_asset_bundle(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert replay.items[0].value == 0
    finally:
        assert not scope.close() and runtime.budget.used == 0
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(
        scope,
        run_id="limited",
        policy=policy(max_live_array_bytes=1, max_decoded_bytes=1),
    )
    try:
        with pytest.raises(InvalidRequestError, match="预算"):
            read_asset_bundle(
                runtime,
                asset,
                service=service,
                project_id="test",
                policy=POLICY,
                cancel=lambda: None,
            )
        assert runtime.budget.used == 0 and runtime.storage_scope.resource_count == 0
    finally:
        assert not scope.close()


@pytest.mark.parametrize("failure", [OSError, InterruptedError])
def test_relation_write_failure_never_commits_half_asset(
    tmp_path, monkeypatch, failure
):
    """原云已写出后关系块中断，不得遗留可见版本或半个不可变目录。"""
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[0, -2, 0], [0, 2, 0], [4, -2, 0], [4, 2, 0]], dtype=float
        ),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    service = create_resource_service(tmp_path)
    try:
        features = analytic_edges(runtime, root)
        evidence = relation_evidence(
            runtime, root, [features], parameters("line-line"), cancel=lambda: None
        )
        original = service.storage.write_immutable_stream
        prefixes = []

        def interrupted(**kwargs):
            prefixes.append(kwargs["object_prefix"])
            if kwargs["source_stream"].blob.role == "relation":
                kwargs["source_stream"].read(1)
                raise failure("injected relation write failure")
            return original(**kwargs)

        monkeypatch.setattr(service.storage, "write_immutable_stream", interrupted)
        from backend.service.application.errors import PersistenceOperationError

        with pytest.raises(
            PersistenceOperationError if failure is OSError else failure
        ):
            save_cloud(
                runtime,
                root,
                features=features,
                evidence=evidence,
                service=service,
                project_id="test",
                mode="derived",
                name="atomic",
                write_identity="8" * 64,
                policy=POLICY,
                cancel=lambda: None,
            )
        assert not service.list_versions(project_id="test")
        assert prefixes and all(
            not service.storage.resolve(prefix + "/immutable").exists()
            for prefix in prefixes
        )
        with runtime.borrow(root) as view:
            assert len(view.chunk(0, 1)["positions"]) == 1
    finally:
        assert not scope.close() and runtime.budget.used == 0
