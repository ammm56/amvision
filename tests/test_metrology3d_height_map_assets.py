"""高度图随云保存/恢复、坏数据与取消回收；使用实际资源服务。"""

from dataclasses import replace
from io import BytesIO

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.height_map import cloud_to_height_map
from custom_nodes.metrology3d_nodes.shared.height_map_assets import read_height_map
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_height_map import parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_assets import POLICY as BASE_POLICY

POLICY = replace(BASE_POLICY, chunk_bytes=128)


def setup_cloud():
    """有限源点含有效零高度、空格与外点，所有参数只用于测试。"""
    return make_cloud(
        unit="mm",
        coordinates=np.array(
            [
                [0, 0, 0],
                [0.1, 0, 2],
                [1, 0, 3],
                [9, 9, -4],
            ],
            dtype="f4",
        ),
        runtime_policy=policy(max_working_bytes=1_000_000),
    )


def test_pose_evidence_survives_closed_run_without_becoming_live_pose(tmp_path):
    """倾斜坐标变换只作历史证据恢复，数值与来源不重新计算。"""
    from backend.contracts.workflows.height_map3d import HeightMapParameters
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from tests.test_metrology3d_pose_query import tilted_fixture

    scope, runtime, cloud, _, pose, _, _, _ = tilted_fixture()
    other = ResourceScope(kind="height-map-restore")
    target = get_cloud_runtime(
        other,
        run_id="restored",
        policy=runtime.policy.model_copy(update={"max_decoded_bytes": 100000}),
    )
    service = create_resource_service(tmp_path)
    limits = replace(POLICY, max_asset_bytes=100000, max_archive_bytes=120000)
    try:
        raw = parameters().model_dump()
        raw.update(
            frame=dict(
                kind="pose-frame",
                pose_id=pose.pose_id,
                target_frame_id=pose.target_frame_id,
            ),
            width=9,
            height=9,
        )
        raw["grid"].update(origin=(-2, -2, 0), column_step=0.5, row_step=0.5)
        result = cloud_to_height_map(
            runtime,
            cloud,
            HeightMapParameters.model_validate(raw),
            pose=pose,
            cancel=lambda: None,
        )
        with result.borrow(runtime) as arrays:
            expected = {k: v.tobytes() for k, v in arrays.items()}
        asset = save_cloud(
            runtime,
            cloud,
            height_map=result,
            service=service,
            project_id="test",
            name="posed",
            mode="derived",
            write_identity="f" * 64,
            policy=limits,
            cancel=lambda: None,
        )
        assert scope.close() == () and runtime.budget.used == 0
        doc = service.read(asset, project_id="test")
        loaded = read_asset(
            target,
            asset,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        restored = read_height_map(
            target,
            loaded,
            document=doc,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        with restored.borrow(target) as arrays:
            assert {k: v.tobytes() for k, v in arrays.items()} == expected
        assert restored.pose_json == result.pose_json
        with pytest.raises(InvalidRequestError):
            cloud_to_height_map(
                target,
                loaded,
                HeightMapParameters.model_validate(raw),
                pose=pose,
                cancel=lambda: None,
            )
    finally:
        assert scope.close() == () and other.close() == () and target.budget.used == 0


def test_original_file_asset_materializes_when_height_map_is_added(tmp_path):
    """原件读回后增加高度图必须转为派生块，不丢原字段别名和源行。"""
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
    from tests.point_cloud_support import options
    from tests.integration.metrology3d.test_file_read import publish, ply

    service = create_resource_service(tmp_path)
    scope = ResourceScope(kind="original-height-map")
    runtime = get_cloud_runtime(
        scope, run_id="original", policy=policy(max_working_bytes=1_000_000)
    )
    try:
        source = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=publish(service.storage, ply(b"0 0 0\n1 0 3\n", count=2)),
            options=options(),
            cancel=lambda: None,
        )
        original = save_cloud(
            runtime,
            source,
            service=service,
            project_id="test",
            name="original",
            mode="original",
            write_identity="e" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        cloud = read_asset(
            runtime,
            original,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        derived = save(runtime, cloud, result, service)
        doc = service.read(derived, project_id="test")
        assert doc.content.point_cloud.representation == "array-blocks"
        assert doc.content.point_cloud.height_map.input_count == 2
        loaded = read_asset(
            runtime,
            derived,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        reopened = read_height_map(
            runtime,
            loaded,
            document=doc,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        with reopened.borrow(runtime) as arrays:
            np.testing.assert_array_equal(arrays["source_rows"][:, 0], [0, 1])
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def save(runtime, cloud, result, service, identity="a"):
    return save_cloud(
        runtime,
        cloud,
        service=service,
        project_id="test",
        name="height-map",
        mode="derived",
        write_identity=identity * 64,
        policy=POLICY,
        cancel=lambda: None,
        height_map=result,
    )


def test_height_map_recipe_package_imports_into_empty_store(tmp_path):
    """A10 依赖闭包搬运的是完整高度资产，空环境不依赖旧 Run。"""
    from backend.contracts.workflows.cloud_package import WorkflowAppDocument
    from backend.service.application.workflows.cloud_package import export_cloud_package
    from backend.service.application.workflows.documents.measurement_resources import (
        reference_key,
    )
    from tests.test_workflow_cloud_package import workflow_service, import_package
    from tests.integration.metrology3d.test_height_map_published import documents

    scope, runtime, cloud = setup_cloud()
    service = create_resource_service(tmp_path / "source")
    other = create_resource_service(tmp_path / "destination")
    limits = replace(POLICY, max_archive_bytes=1_000_000)
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        asset = save(runtime, cloud, result, service)
        template, application = documents(reference=asset.model_dump(mode="json"))
        stream = BytesIO()
        export_cloud_package(
            workflow_service(service),
            WorkflowAppDocument(
                format_id="amvision.workflow-app-document.v1",
                template=template,
                application=application,
            ),
            project_id="test",
            stream=stream,
            policy=limits,
            cancel=lambda: None,
        )
        _, mapping = import_package(other, limits, stream.getvalue())
        imported = mapping[reference_key(asset)]
        assert imported != asset
        restored_cloud = read_asset(
            runtime,
            imported,
            service=other,
            project_id="target",
            policy=limits,
            cancel=lambda: None,
        )
        restored_map = read_height_map(
            runtime,
            restored_cloud,
            document=other.read(imported, project_id="target"),
            service=other,
            project_id="target",
            policy=limits,
            cancel=lambda: None,
        )
        with result.borrow(runtime) as before, restored_map.borrow(runtime) as after:
            assert {k: v.tobytes() for k, v in before.items()} == {
                k: v.tobytes() for k, v in after.items()
            }
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("aggregation", ["minimum", "maximum", "mean", "median"])
def test_output_roundtrip_archive_and_save_again(tmp_path, aggregation):
    service = create_resource_service(tmp_path)
    scope, runtime, cloud = setup_cloud()
    try:
        original = cloud_to_height_map(
            runtime, cloud, parameters(aggregation), cancel=lambda: None
        )
        asset = save(runtime, cloud, original, service)
        document = service.read(asset, project_id="test")
        assert document.content.point_cloud.height_map.occupied_count == 2
        loaded = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        result = read_height_map(
            runtime,
            loaded,
            document=document,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        with original.borrow(runtime) as a, result.borrow(runtime) as b:
            assert set(a) == set(b)
            for key in a:
                assert a[key].tobytes() == b[key].tobytes()
        second = save(runtime, loaded, result, service, "b")
        assert second.sha256 == asset.sha256
        archive = BytesIO()
        service.export_cloud_archive(
            asset, project_id="test", stream=archive, policy=POLICY, cancel=lambda: None
        )
        imported = service.import_cloud_archive(
            stream=archive,
            project_id="other",
            name="height-map",
            write_identity="c" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        assert imported.reference.sha256 == asset.sha256
        foreign = read_asset(
            runtime,
            imported.reference,
            service=service,
            project_id="other",
            policy=POLICY,
            cancel=lambda: None,
        )
        reopened = read_height_map(
            runtime,
            foreign,
            document=imported,
            service=service,
            project_id="other",
            policy=POLICY,
            cancel=lambda: None,
        )
        with reopened.borrow(runtime) as values:
            assert values["counts"].sum() == 3
            assert np.isnan(values["heights"][2, 0])
        with pytest.raises(InvalidRequestError):
            read_height_map(
                runtime,
                foreign,
                document=document,
                service=service,
                project_id="test",
                policy=POLICY,
                cancel=lambda: None,
            )
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def test_restore_every_cancel_point_releases_output(tmp_path):
    service = create_resource_service(tmp_path)
    scope, runtime, cloud = setup_cloud()
    try:
        original = cloud_to_height_map(
            runtime, cloud, parameters(), cancel=lambda: None
        )
        asset = save(runtime, cloud, original, service)
        document = service.read(asset, project_id="test")
        loaded = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        baseline, calls = runtime.budget.used, 0

        def count():
            nonlocal calls
            calls += 1

        result = read_height_map(
            runtime,
            loaded,
            document=document,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=count,
        )
        runtime.storage_scope.close_resource(result.resource_key)
        for fail_at in range(1, calls + 1):
            counter = 0

            def cancel():
                nonlocal counter
                counter += 1
                if counter == fail_at:
                    raise InterruptedError("cancel")

            with pytest.raises(InterruptedError):
                read_height_map(
                    runtime,
                    loaded,
                    document=document,
                    service=service,
                    project_id="test",
                    policy=POLICY,
                    cancel=cancel,
                )
            assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_restore_budget_and_wrong_source_rejected(tmp_path):
    service = create_resource_service(tmp_path)
    scope, runtime, cloud = setup_cloud()
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        with pytest.raises(InvalidRequestError):
            save_cloud(
                runtime,
                cloud,
                service=service,
                project_id="test",
                name="bad",
                mode="original",
                write_identity="f" * 64,
                policy=POLICY,
                cancel=lambda: None,
                height_map=result,
            )
        assert service.list_versions(project_id="test") == []
        asset = save(runtime, cloud, result, service)
        doc = service.read(asset, project_id="test")
        loaded = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        baseline = runtime.budget.used
        with pytest.raises(InvalidRequestError):
            read_height_map(
                runtime,
                loaded,
                document=doc,
                service=service,
                project_id="test",
                policy=replace(POLICY, max_asset_bytes=8, chunk_bytes=8),
                cancel=lambda: None,
            )
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize(
    "failure", ["truncated", "extra", "counts", "offsets", "infinite", "indices"]
)
def test_corrupt_archive_rejected_without_committed_version(tmp_path, failure):
    from hashlib import sha256
    from zipfile import ZipFile, ZIP_STORED
    import json

    service = create_resource_service(tmp_path)
    scope, runtime, cloud = setup_cloud()
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        asset = save(runtime, cloud, result, service)
        archive = BytesIO()
        service.export_cloud_archive(
            asset, project_id="test", stream=archive, policy=POLICY, cancel=lambda: None
        )
        with ZipFile(archive) as source:
            contents = {name: source.read(name) for name in source.namelist()}
        body = json.loads(contents["resource.json"])
        data = bytearray(contents["height-map.bin"])
        evidence = service.read(asset, project_id="test").content.point_cloud.height_map
        offsets, cursor = {}, 0
        for name, dtype, count in evidence.layout():
            offsets[name] = cursor
            cursor += np.dtype(dtype).itemsize * count
        if failure == "truncated":
            data = data[:-1]
        elif failure == "extra":
            data += b"x"
        elif failure == "infinite":
            data[:4] = np.array([np.inf], dtype="<f4").tobytes()
        else:
            name = {
                "counts": "counts",
                "offsets": "member_offsets",
                "indices": "input_rows",
            }[failure]
            value = 4 if failure == "indices" else 1
            data[offsets[name] : offsets[name] + 8] = np.array(
                [value], dtype="<u8"
            ).tobytes()
        for blob in body["point_cloud"]["blobs"]:
            if blob["role"] == "height-map":
                # 即使攻击者重算摘要，值域和结构仍须拒绝。
                blob["sha256"] = sha256(data).hexdigest()
        contents["resource.json"] = json.dumps(body).encode()
        contents["height-map.bin"] = data
        corrupted = BytesIO()
        with ZipFile(corrupted, "w", compression=ZIP_STORED) as target:
            for name, value in contents.items():
                target.writestr(name, value)
        with pytest.raises(InvalidRequestError):
            service.import_cloud_archive(
                stream=corrupted,
                project_id="empty",
                name="bad",
                write_identity="d" * 64,
                policy=replace(POLICY, chunk_bytes=7),
                cancel=lambda: None,
            )
        assert service.list_versions(project_id="empty") == []
    finally:
        assert scope.close() == ()


def test_save_cancellation_rolls_back_data(tmp_path):
    service = create_resource_service(tmp_path)
    scope, runtime, cloud = setup_cloud()
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        original_write = service.storage.write_json

        def cancel_commit(key, value, *args, **kwargs):
            if key.endswith("version.json"):
                raise InterruptedError("before commit")
            return original_write(key, value, *args, **kwargs)

        service.storage.write_json = cancel_commit
        baseline = runtime.budget.used
        with pytest.raises(InterruptedError):
            save(runtime, cloud, result, service)
        assert service.list_versions(project_id="test") == []
        assert not list(tmp_path.rglob("content.bin"))
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("kind", ["surface", "grid-profile", "voxel-aggregate"])
def test_generated_lineage_survives_original_scope_close(tmp_path, kind):
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from backend.contracts.workflows.height_map3d import HeightMapParameters

    if kind == "voxel-aggregate":
        from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
        from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters

        scope, runtime, parent = setup_cloud()
        sampling = ResampleCloudParameters(
            settings=dict(
                kind="voxel-centroid",
                grid_origin=(0, 0, 0),
                voxel_size=10,
                frame_id="fixture",
                length_unit="mm",
                max_position_error=1e-5,
                attributes="positions-only",
            )
        )
        cloud, _ = resample_cloud(runtime, parent, sampling, cancel=lambda: None)
    else:
        if kind == "surface":
            from tests.test_metrology3d_dynamic_contour import fixture, extract
        else:
            from tests.integration.metrology3d.test_envelope_runtime import (
                fixture,
                extract,
            )
        values, p, measured = fixture()
        scope, runtime, *_ = values
        group = extract(values, p, measured)
        assert group.items[0].valid
        cloud = group.items[0].support
    limits = runtime.policy
    service = create_resource_service(tmp_path)
    assets = replace(POLICY, max_asset_bytes=1_000_000, max_archive_bytes=2_000_000)
    try:
        raw = parameters().model_dump()
        if kind != "voxel-aggregate":
            raw.update(width=20, height=20)
            raw["grid"].update(origin=(-50, -50, 0), column_step=10, row_step=10)
        result = cloud_to_height_map(
            runtime, cloud, HeightMapParameters.model_validate(raw), cancel=lambda: None
        )
        with result.borrow(runtime) as arrays:
            expected = {k: v.tobytes() for k, v in arrays.items()}
            assert "source_rows" not in arrays
        with runtime.borrow(cloud) as view:
            lineage = [
                {
                    k: a.tobytes()
                    for k, a in view.lineage_chunk(
                        start, min(start + limits.chunk_rows, cloud.point_count)
                    ).items()
                }
                for start in range(0, cloud.point_count, limits.chunk_rows)
            ]
        count = runtime.source_point_count(cloud)
        reference = save_cloud(
            runtime,
            cloud,
            height_map=result,
            service=service,
            project_id="test",
            name="generated",
            mode="derived",
            write_identity="e" * 64,
            policy=assets,
            cancel=lambda: None,
        )
    finally:
        assert scope.close() == () and runtime.budget.used == 0
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="restored", policy=limits)
    try:
        loaded = read_asset(
            runtime,
            reference,
            service=service,
            project_id="test",
            policy=assets,
            cancel=lambda: None,
        )
        restored = read_height_map(
            runtime,
            loaded,
            document=service.read(reference, project_id="test"),
            service=service,
            project_id="test",
            policy=assets,
            cancel=lambda: None,
        )
        assert (
            loaded.lineage_kind == kind and runtime.source_point_count(loaded) == count
        )
        with restored.borrow(runtime) as arrays:
            assert expected == {k: v.tobytes() for k, v in arrays.items()}
        with runtime.borrow(loaded) as view:
            assert lineage == [
                {
                    k: a.tobytes()
                    for k, a in view.lineage_chunk(
                        start, min(start + limits.chunk_rows, loaded.point_count)
                    ).items()
                }
                for start in range(0, loaded.point_count, limits.chunk_rows)
            ]
    finally:
        assert scope.close() == () and runtime.budget.used == 0
