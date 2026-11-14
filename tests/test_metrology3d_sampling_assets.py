"""采样诊断沿真实资源服务保存、搬运、恢复和拒绝损坏，不重算原因。"""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_STORED

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.point_cloud.sampling_bytes import (
    SAMPLING_DTYPE,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.edge_sampling import sampling_candidates
from custom_nodes.metrology3d_nodes.shared.edge_sampling_context import sampling_context
from custom_nodes.metrology3d_nodes.shared.edge_sampling_assets import read_sampling
from tests.point_cloud_support import create_resource_service
from tests.test_point_cloud_assets import POLICY as BASE_POLICY
from tests.test_metrology3d_sampling import prepare

POLICY = replace(
    BASE_POLICY, chunk_bytes=127, max_asset_bytes=100000, max_archive_bytes=200000
)


def save(runtime, cloud, diagnostic, service, identity="a"):
    """使用同一正式事务入口，不直接写资产文件。"""
    return save_cloud(
        runtime,
        cloud,
        sampling=diagnostic,
        service=service,
        project_id="test",
        name="sampling",
        mode="derived",
        write_identity=identity * 64,
        policy=POLICY,
        cancel=lambda: None,
    )


def fixture(tmp_path):
    """真实 B03、采样原生算子及来源分类，不构造假候选。"""
    scope, runtime, _, cloud, settings, _ = prepare()
    service = create_resource_service(tmp_path)
    try:
        candidates = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        diagnostic = sampling_context(runtime, candidates, cancel=lambda: None)
        return scope, runtime, cloud, diagnostic, service
    except BaseException:
        scope.close()
        raise


def test_roundtrip_new_run_empty_store_and_save_again(tmp_path):
    scope, runtime, cloud, result, service = fixture(tmp_path / "source")
    target_scope = ResourceScope(kind="sampling-restore")
    target = get_cloud_runtime(target_scope, run_id="restored", policy=runtime.policy)
    other = create_resource_service(tmp_path / "target")
    try:
        with result.borrow(runtime) as (data, facts):
            expected = {k: v.tobytes() for k, v in {**data, **facts}.items()}
        asset = save(runtime, cloud, result, service)
        archive = BytesIO()
        service.export_cloud_archive(
            asset, project_id="test", stream=archive, policy=POLICY, cancel=lambda: None
        )
        assert scope.close() == () and runtime.budget.used == 0
        doc = other.import_cloud_archive(
            stream=archive,
            project_id="test",
            name="imported",
            write_identity="b" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        assert doc.reference.sha256 == asset.sha256
        loaded = read_asset(
            target,
            doc.reference,
            service=other,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        restored = read_sampling(
            target,
            loaded,
            document=doc,
            service=other,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        with restored.borrow(target) as (data, facts):
            assert {k: v.tobytes() for k, v in {**data, **facts}.items()} == expected
            assert not any(a.flags.writeable for a in data.values())
        assert not hasattr(restored, "geometry")
        assert save(target, loaded, restored, other, "c").sha256 == doc.reference.sha256
        with pytest.raises(InvalidRequestError):
            read_sampling(
                target,
                cloud,
                document=doc,
                service=other,
                project_id="test",
                policy=POLICY,
                cancel=lambda: None,
            )
    finally:
        assert scope.close() == () and target_scope.close() == ()
        assert target.budget.used == 0


def test_existing_recipe_package_carries_sampling_without_runtime_handles(tmp_path):
    """A10 原资源闭包自动搬运新证据块，空库重新映射后仍可严格恢复。"""
    from backend.contracts.workflows.cloud_package import WorkflowAppDocument
    from backend.service.application.workflows.cloud_package import export_cloud_package
    from backend.service.application.workflows.documents.measurement_resources import (
        reference_key,
    )
    from tests.test_workflow_cloud_package import workflow_service, import_package
    from tests.integration.metrology3d.test_height_map_published import documents

    scope, runtime, cloud, result, service = fixture(tmp_path / "source")
    other = create_resource_service(tmp_path / "target")
    limits = replace(POLICY, max_archive_bytes=1_000_000)
    try:
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
        mapped = mapping[reference_key(asset)]
        assert mapped != asset
        loaded = read_asset(
            runtime,
            mapped,
            service=other,
            project_id="target",
            policy=limits,
            cancel=lambda: None,
        )
        restored = read_sampling(
            runtime,
            loaded,
            document=other.read(mapped, project_id="target"),
            service=other,
            project_id="target",
            policy=limits,
            cancel=lambda: None,
        )
        with result.borrow(runtime) as (a, af), restored.borrow(runtime) as (b, bf):
            for name, values in {**a, **af}.items():
                np.testing.assert_array_equal(values, {**b, **bf}[name])
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize(
    "fault", ["short", "extra", "identity", "status", "context", "neighbors", "total"]
)
def test_corruption_rejected_even_with_updated_digest(tmp_path, fault):
    scope, runtime, cloud, result, service = fixture(tmp_path)
    try:
        asset = save(runtime, cloud, result, service)
        archive = BytesIO()
        service.export_cloud_archive(
            asset, project_id="test", stream=archive, policy=POLICY, cancel=lambda: None
        )
        with ZipFile(archive) as z:
            files = {name: z.read(name) for name in z.namelist()}
        body = json.loads(files["resource.json"])
        records = np.frombuffer(files["sampling.bin"], dtype=SAMPLING_DTYPE).copy()
        if fault == "identity":
            records["identity_rows"][0] = 999999
        elif fault == "status":
            records["status"][0] = 32
        elif fault == "context":
            records["context"][0] = 3
        elif fault == "neighbors":
            records["neighbors"][0] = 0
        elif fault == "total":
            body["point_cloud"]["sampling"]["candidate_count"] += 1
        data = records.tobytes()
        if fault == "short":
            data = data[:-1]
        if fault == "extra":
            data += b"x"
        for b in body["point_cloud"]["blobs"]:
            if b["role"] == "sampling":
                b["sha256"] = sha256(data).hexdigest()
        files["sampling.bin"] = data
        files["resource.json"] = json.dumps(body).encode()
        corrupted = BytesIO()
        with ZipFile(corrupted, "w", compression=ZIP_STORED) as z:
            for name, payload in files.items():
                z.writestr(name, payload)
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


def test_each_restore_cancellation_releases_new_owner(tmp_path):
    scope, runtime, cloud, result, service = fixture(tmp_path)
    try:
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
        calls = 0

        def count():
            nonlocal calls
            calls += 1

        restored = read_sampling(
            runtime,
            loaded,
            document=doc,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=count,
        )
        runtime.storage_scope.close_resource(restored.resource_key)
        baseline = runtime.budget.used
        for stop in range(1, calls + 1):
            index = 0

            def cancel():
                nonlocal index
                index += 1
                if index == stop:
                    raise InterruptedError("cancel")

            with pytest.raises(InterruptedError):
                read_sampling(
                    runtime,
                    loaded,
                    document=doc,
                    service=service,
                    project_id="test",
                    policy=POLICY,
                    cancel=cancel,
                )
            assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_save_commit_cancel_removes_partial_blobs(tmp_path):
    scope, runtime, cloud, result, service = fixture(tmp_path)
    try:
        original = service.storage.write_json

        def cancelled(key, value, *args, **kwargs):
            if key.endswith("version.json"):
                raise InterruptedError("commit")
            return original(key, value, *args, **kwargs)

        service.storage.write_json = cancelled
        baseline = runtime.budget.used
        with pytest.raises(InterruptedError):
            save(runtime, cloud, result, service)
        assert service.list_versions(project_id="test") == []
        assert not list(tmp_path.rglob("content.bin"))
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("kind", ["source-subset", "voxel-aggregate"])
def test_identity_and_generated_lineage_roundtrip(tmp_path, kind):
    """源子集保持最初行号，体素点保持成员关系，不能二次编号冒充原始点。"""
    from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
    from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals
    from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
    from tests.integration.metrology3d.representative_recipe import boxes
    from tests.test_metrology3d_normal_estimation import parameters

    scope, runtime, original, _, settings, _ = prepare()
    service = create_resource_service(tmp_path)
    try:
        if kind == "source-subset":
            cloud, _ = crop_roi(
                runtime,
                original,
                boxes("test", [[1, 5, 0, 6, -1, 1]]),
                cancel=lambda: None,
            )
        else:
            cloud, _ = resample_cloud(
                runtime,
                original,
                ResampleCloudParameters(
                    settings=dict(
                        kind="voxel-centroid",
                        grid_origin=(0, 0, 0),
                        voxel_size=1,
                        frame_id=original.spatial.frame_id,
                        length_unit="mm",
                        max_position_error=1e-5,
                        attributes="positions-only",
                    )
                ),
                cancel=lambda: None,
            )
        cloud, _ = estimate_normals(
            runtime,
            cloud,
            parameters(
                "radius",
                neighborhood=dict(kind="radius", radius=1.8),
                frame_id=cloud.spatial.frame_id,
            ),
            cancel=lambda: None,
        )
        result = sampling_context(
            runtime,
            sampling_candidates(runtime, cloud, settings, cancel=lambda: None),
            cancel=lambda: None,
        )
        asset = save(runtime, cloud, result, service)
        document = service.read(asset, project_id="test")
        loaded = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        restored = read_sampling(
            runtime,
            loaded,
            document=document,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert runtime.source_point_count(loaded) == original.point_count
        if kind == "voxel-aggregate":
            assert document.content.point_cloud.lineage.kind == "voxel-aggregate"
            assert loaded.vertex_kind == "generated"
        with result.borrow(runtime) as (a, af), restored.borrow(runtime) as (b, bf):
            for name, values in {**a, **af}.items():
                np.testing.assert_array_equal(values, {**b, **bf}[name])
    finally:
        assert scope.close() == ()
