"""标定标量到当前点云、过滤和真实资产存读；不冒充节点发布页面验收。"""

from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import weakref

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    FilterCloudValid,
)
from backend.contracts.workflows.measurement_resources import MeasurementResourceContent
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.point_cloud.raster_buffer import (
    raster_descriptor_sha256,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    cloud_blob_key,
)
from backend.service.application.workflows.documents.cloud_resource_archives import (
    export_cloud_archive,
    import_cloud_archive,
)
from custom_nodes.metrology3d_nodes.shared.io.read_raster import (
    read_raster_reference,
    read_raster_local,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from tests.point_cloud_support import create_resource_service, policy
from tests.test_point_cloud_assets import POLICY as BASE_POLICY
from tests.test_metrology3d_raster_io import encode
from tests.test_metrology3d_raster_conversion import specification
from tests.test_metrology3d_raster_buffer import arena_input as arena_input, descriptor
from tests.integration.metrology3d.test_file_read import publish

POLICY = replace(BASE_POLICY, chunk_bytes=256)


@pytest.fixture
def context(tmp_path, request):
    """每个测试均有独立运行身份、对象仓库和显式小预算。"""
    scope = ResourceScope(kind="raster-runtime")
    runtime = get_cloud_runtime(
        scope,
        run_id="raster-test",
        policy=policy(chunk_rows=12, **getattr(request, "param", {})),
    )
    service = create_resource_service(tmp_path)
    try:
        yield runtime, service
    finally:
        assert scope.close() == ()
        assert runtime.budget.used == 0


def save(runtime, reference, service, mode, identity):
    """沿现有 Save Cloud 核心保存，不直接构造成功 manifest。"""
    return save_cloud(
        runtime,
        reference,
        service=service,
        project_id="test",
        name="raster",
        mode=mode,
        write_identity=identity * 64,
        policy=POLICY,
        cancel=lambda: None,
    )


def restored(runtime, ref, service):
    """重读重新取得本次运行身份，旧 cloud ID 不带访问权。"""
    return read_asset(
        runtime,
        ref,
        service=service,
        project_id="test",
        policy=POLICY,
        cancel=lambda: None,
    )


def package_roundtrip(runtime, ref, service, tmp_path):
    """持久父链使用既有 A10 配方包搬运，不把单资产 ZIP 当依赖闭包。"""
    from backend.contracts.workflows.cloud_package import WorkflowAppDocument
    from backend.service.application.workflows.cloud_package import export_cloud_package
    from backend.service.application.workflows.documents.measurement_resources import (
        reference_key,
    )
    from tests.test_workflow_cloud_package import workflow_service, import_package
    from tests.metrology3d_transport_support import cloud_documents
    from tests.point_cloud_support import options

    template, application = cloud_documents(options().model_dump(mode="json"))
    template = template.model_dump(mode="json")
    application = application.model_dump(mode="json")
    template["nodes"][0]["parameters"] = {
        "source": {
            "kind": "asset",
            "reference": ref.model_dump(mode="json"),
        }
    }
    template["template_inputs"] = []
    application["bindings"] = [
        b for b in application["bindings"] if b["direction"] == "output"
    ]
    stream = BytesIO()
    policy = replace(POLICY, max_archive_bytes=1_000_000)
    export_cloud_package(
        workflow_service(service),
        WorkflowAppDocument(
            format_id="amvision.workflow-app-document.v1",
            application=application,
            template=template,
        ),
        project_id="test",
        stream=stream,
        policy=policy,
        cancel=lambda: None,
    )
    other = create_resource_service(tmp_path / "other")
    _, mapping = import_package(other, policy, stream.getvalue())
    assert len(mapping) == 3
    imported = mapping[reference_key(ref)]
    cloud = read_asset(
        runtime,
        imported,
        service=other,
        project_id="target",
        policy=policy,
        cancel=lambda: None,
    )
    return cloud, other.read(imported, project_id="target").content


def compare(runtime, first, second):
    """全部字段按字节核对，包含 NaN 位模式与原始行号。"""
    assert first.cloud_id != second.cloud_id
    assert runtime.source_point_count(first) == runtime.source_point_count(second)
    assert runtime.raster_source(first) == runtime.raster_source(second)
    assert runtime.raster_source(first) is not None
    with runtime.borrow(first) as a, runtime.borrow(second) as b:
        for key, value in a.chunk(0, first.point_count).items():
            assert value.tobytes() == b.chunk(0, second.point_count)[key].tobytes()
        np.testing.assert_array_equal(
            a.source_indices(0, first.point_count),
            b.source_indices(0, second.point_count),
        )


@pytest.mark.parametrize(
    "kind,dtype", [("npy", "float64"), ("png", "uint16"), ("tiff", "float32")]
)
def test_file_original_and_derived_preserve_calibration_and_pixel_identity(
    context, kind, dtype
):
    runtime, service = context
    array = np.arange(12, dtype=dtype).reshape(3, 4)
    encoded = encode(array, kind)
    source, counts = read_raster_reference(
        runtime=runtime,
        object_store=service.storage,
        project_id="test",
        file=publish(service.storage, encoded),
        file_format=kind,
        spec=specification(dtype=dtype),
        cancel=lambda: None,
    )
    assert source.point_count == runtime.source_point_count(source) == 12
    assert sum(counts.values()) == 12
    assert counts["valid"] == 11
    original = save(runtime, source, service, "original", "a")
    document = service.read(original, project_id="test")
    cloud = document.content.point_cloud
    assert cloud.representation == "raster-original"
    assert cloud.source.raster == source.source.raster
    assert "file" not in cloud.source.model_dump()
    with service.storage.open_read_snapshot(
        cloud_blob_key(service, original, cloud.blobs[0])
    ) as snapshot:
        assert snapshot.stream.read() == encoded
    compare(runtime, source, restored(runtime, original, service))
    selected, summary = filter_valid(
        runtime,
        source,
        FilterCloudValid(finite_fields=("positions",), sentinels=()),
        cancel=lambda: None,
    )
    assert summary["kept_count"] == 11
    filtered = save(runtime, selected, service, "derived", "b")
    cloud = service.read(filtered, project_id="test").content.point_cloud
    assert cloud.indices.source_point_count == 12
    assert cloud.indices.source.raster == source.source.raster
    compare(runtime, selected, restored(runtime, filtered, service))
    # 当前派生结果的“保存原始”仍保存原文件，而不是过滤后的坐标。
    original_again = save(runtime, selected, service, "original", "c")
    assert service.read(original_again, project_id="test").content == document.content


def test_real_mmap_to_asset_and_filter_retains_full_pixel_ids(context, arena_input):
    runtime, service = context
    arena, receipt, acquire = arena_input
    source, counts = read_raster_local(
        runtime=runtime,
        descriptor=descriptor(),
        expected_descriptor_sha256=raster_descriptor_sha256(descriptor()),
        acquire_view=acquire,
        cancel=lambda: None,
    )
    assert arena.request_reclaim(receipt) == "released"
    assert sum(counts.values()) == 12
    assert counts["valid"] == 10
    ref = save(runtime, source, service, "original", "a")
    content = service.read(ref, project_id="test").content.point_cloud
    assert content.representation == "array-blocks" and content.source.has_mask
    compare(runtime, source, restored(runtime, ref, service))
    selected, _ = filter_valid(
        runtime,
        source,
        FilterCloudValid(finite_fields=("positions",), sentinels=()),
        cancel=lambda: None,
    )
    with runtime.borrow(selected) as view:
        np.testing.assert_array_equal(view.source_indices(0, 10), np.arange(2, 12))
    compare(
        runtime,
        selected,
        restored(runtime, save(runtime, selected, service, "derived", "b"), service),
    )


def test_raster_source_tamper_and_cross_run_rejected(context):
    runtime, service = context
    source, _ = read_raster_reference(
        runtime=runtime,
        object_store=service.storage,
        project_id="test",
        file=publish(service.storage, encode(np.ones((3, 4), dtype="float32"), "npy")),
        file_format="npy",
        spec=specification(),
        cancel=lambda: None,
    )
    payload = source.model_dump(mode="json")
    changed = deepcopy(payload)
    changed["source"]["raster"]["projection"]["fx"] = 5
    for changed in (changed, {**payload, "run_id": "another"}):
        with pytest.raises(InvalidRequestError):
            with runtime.borrow(CloudReference.model_validate(changed)):
                pytest.fail("unregistered source")
    changed = deepcopy(payload)
    changed["source"]["raster"]["width"] = 3
    with pytest.raises(ValidationError):
        CloudReference.model_validate(changed)
    doc = service.read(
        save(runtime, source, service, "original", "a"), project_id="test"
    )
    changed = doc.content.model_dump(mode="json")
    changed["point_cloud"]["source"]["content_sha256"] = "f" * 64
    with pytest.raises(ValidationError):
        MeasurementResourceContent.model_validate(changed)


def test_raster_original_archive_import_empty_store(context, tmp_path):
    runtime, service = context
    source, _ = read_raster_reference(
        runtime=runtime,
        object_store=service.storage,
        project_id="test",
        file=publish(service.storage, encode(np.ones((3, 4), dtype="float32"), "npy")),
        file_format="npy",
        spec=specification(),
        cancel=lambda: None,
    )
    ref = save(runtime, source, service, "original", "a")
    stream = BytesIO()
    export_cloud_archive(
        service,
        ref,
        project_id="test",
        stream=stream,
        policy=POLICY,
        cancel=lambda: None,
    )
    other = create_resource_service(tmp_path / "other")
    stream.seek(0)
    imported = import_cloud_archive(
        other,
        stream=stream,
        project_id="test",
        name="imported",
        write_identity="b" * 64,
        policy=POLICY,
        cancel=lambda: None,
    )
    compare(runtime, source, restored(runtime, imported.reference, other))


@pytest.mark.parametrize("mode", ["original", "derived"])
@pytest.mark.parametrize("entry", ["file", "array"])
def test_repeated_asset_derivation_retains_raster_origin(
    context, arena_input, mode, entry
):
    """原件/数组块重读后多次派生，保留全部标定、原值和最初像素身份。"""
    runtime, service = context
    arena, receipt, acquire = arena_input
    if entry == "file":
        source, _ = read_raster_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=publish(
                service.storage, encode(np.arange(12, dtype="f4").reshape(3, 4), "npy")
            ),
            file_format="npy",
            spec=specification(),
            cancel=lambda: None,
        )
    else:
        source, _ = read_raster_local(
            runtime=runtime,
            descriptor=descriptor(),
            expected_descriptor_sha256=raster_descriptor_sha256(descriptor()),
            acquire_view=acquire,
            cancel=lambda: None,
        )
    assert arena.request_reclaim(receipt) == "released"
    loaded = restored(runtime, save(runtime, source, service, mode, "a"), service)
    for identity in ("b", "c", "d"):
        selected, _ = filter_valid(
            runtime,
            loaded,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        ref = save(runtime, selected, service, "derived", identity)
        from custom_nodes.metrology3d_nodes.shared.raster_assets import (
            freeze_raster_source,
        )

        assert service.read(
            ref, project_id="test"
        ).content.point_cloud.indices.source == freeze_raster_source(source.source)
        loaded = restored(runtime, ref, service)
        compare(runtime, selected, loaded)
        assert runtime.raster_source(loaded) == runtime.raster_source(source)
        assert runtime.source_point_count(loaded) == 12
        with runtime.borrow(loaded) as view:
            np.testing.assert_array_equal(
                view.source_indices(0, loaded.point_count),
                np.arange(1 if entry == "file" else 2, 12),
            )


@pytest.mark.parametrize("kind", ["stride", "voxel-representative", "voxel-centroid"])
@pytest.mark.parametrize("context", [{"max_working_bytes": 65536}], indirect=True)
def test_restored_raster_resample_preserves_origin_and_archive(context, tmp_path, kind):
    """源点与生成点多代保存及空仓库搬运；生成点不伪造原像素。"""
    from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
    from tests.test_metrology3d_resample import parameters

    runtime, service = context
    source, _ = read_raster_reference(
        runtime=runtime,
        object_store=service.storage,
        project_id="test",
        file=publish(service.storage, encode(np.ones((3, 4), dtype="f4"), "npy")),
        file_format="npy",
        spec=specification(),
        cancel=lambda: None,
    )
    loaded = restored(runtime, save(runtime, source, service, "original", "a"), service)
    params = parameters(kind)
    if kind != "stride":
        params = ResampleCloudParameters(
            settings={
                **params.settings.model_dump(),
                "frame_id": loaded.spatial.frame_id,
            }
        )
    sampled, _ = resample_cloud(runtime, loaded, params, cancel=lambda: None)
    ref = save(runtime, sampled, service, "derived", "b")
    reloaded = restored(runtime, ref, service)
    selected, _ = filter_valid(
        runtime,
        reloaded,
        FilterCloudValid(finite_fields=("positions",), sentinels=()),
        cancel=lambda: None,
    )
    ref = save(runtime, selected, service, "derived", "c")
    roundtrip, imported_content = package_roundtrip(runtime, ref, service, tmp_path)
    assert runtime.raster_source(roundtrip) == source.source.raster
    assert runtime.source_point_count(roundtrip) == 12
    with runtime.borrow(sampled) as a, runtime.borrow(roundtrip) as b:
        for key, value in a.chunk(0, sampled.point_count).items():
            assert value.tobytes() == b.chunk(0, roundtrip.point_count)[key].tobytes()
        if kind == "voxel-centroid":
            for key, value in a.lineage_chunk(0, sampled.point_count).items():
                np.testing.assert_array_equal(
                    value, b.lineage_chunk(0, roundtrip.point_count)[key]
                )
            with pytest.raises(InvalidRequestError, match="唯一"):
                b.source_indices(0, 1)
            bad = imported_content.model_dump(mode="json")
            bad["point_cloud"]["lineage"]["source"]["raster"]["height"] = 4
            with pytest.raises(ValidationError, match="原始总点数"):
                MeasurementResourceContent.model_validate(bad)
        else:
            np.testing.assert_array_equal(
                a.source_indices(0, sampled.point_count),
                b.source_indices(0, roundtrip.point_count),
            )


def test_node_summary_reuses_conversion_counts_without_cloud_rescan(
    context, monkeypatch
):
    """生产 handler 消费同次统计，禁止为摘要再次借用已发布数组。"""
    from types import SimpleNamespace
    from custom_nodes.metrology3d_nodes.backend import raster_handler
    from custom_nodes.metrology3d_nodes.shared.raster_conversion import STATUS_NAMES

    runtime, service = context
    raw = np.array([[np.nan, -3, -2, 0], [1, 2, 3, 4], [5, 6, 7, 8]], dtype="f4")
    values = specification().model_dump(mode="json")
    values["validity"] = dict(invalid_raw_values=[-3.0], minimum=-2.0, maximum=6.0)
    from backend.contracts.workflows.raster3d import CalibratedRaster

    spec = CalibratedRaster.model_validate(values)
    env = SimpleNamespace(
        runtime=runtime, service=service, project_id="test", cancel=lambda: None
    )
    monkeypatch.setattr(raster_handler, "require_node_runtime", lambda _: env)

    def no_rescan(*args, **kwargs):
        pytest.fail("摘要不能再次扫描点云")

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "borrow", no_rescan)
        result = raster_handler.raster_to_cloud(
            SimpleNamespace(
                parameters={
                    "settings": {
                        "kind": "file",
                        "file_format": "npy",
                        "raster": spec.model_dump(mode="json"),
                    }
                },
                input_values={"file": publish(service.storage, encode(raw, "npy"))},
            )
        )
    cloud = CloudReference.model_validate(result["cloud"])
    summary = result["summary"]["value"]
    assert summary["status_counts"] == dict(zip(STATUS_NAMES, (6, 1, 0, 1, 2, 2)))
    assert summary["source_point_count"] == sum(summary["status_counts"].values()) == 12
    with runtime.borrow(cloud) as view:
        actual = np.bincount(view.chunk(0, 12)["sample_status"][:, 0], minlength=6)
    assert summary["status_counts"] == dict(zip(STATUS_NAMES, map(int, actual)))


@pytest.mark.parametrize("context", [{"max_working_bytes": 65536}], indirect=True)
def test_transformed_restored_raster_keeps_capture_frame_and_current_positions(context):
    """采集标定保留原坐标系，不能覆盖变换后的坐标或将其重投影。"""
    from tests.test_metrology3d_transform import cloud_pose
    from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud

    runtime, service = context
    source, _ = read_raster_reference(
        runtime=runtime,
        object_store=service.storage,
        project_id="test",
        file=publish(service.storage, encode(np.full((3, 4), 3, dtype="f4"), "npy")),
        file_format="npy",
        spec=specification(),
        cancel=lambda: None,
    )
    loaded = restored(runtime, save(runtime, source, service, "original", "a"), service)
    _, pose = cloud_pose(runtime, loaded)
    moved = transform_cloud(runtime, loaded, pose, cancel=lambda: None)
    assert moved.state == "ready" and moved.spatial.frame_id == "part"
    result = restored(runtime, save(runtime, moved, service, "derived", "b"), service)
    compare(runtime, moved, result)
    assert runtime.raster_source(result).spatial.frame_id == "fixture"
    assert result.spatial.frame_id == "part"
    with runtime.borrow(loaded) as before, runtime.borrow(result) as after:
        source_points = before.chunk(0, 12)["positions"]
        actual = after.chunk(0, 12)["positions"]
        matrix = np.asarray(pose.transform.matrix)
        np.testing.assert_allclose(
            actual, source_points @ matrix[:3, :3].T + matrix[:3, 3], atol=1e-6
        )


@pytest.mark.parametrize("failure", ["cancel", "budget", "project"])
def test_resaved_raster_failure_preserves_source_and_leaves_no_partial_asset(
    context, failure
):
    """取消、容量拒绝和项目不符不能写出半份来源或释放仍有效的父云。"""
    runtime, service = context
    source, _ = read_raster_reference(
        runtime=runtime,
        object_store=service.storage,
        project_id="test",
        file=publish(
            service.storage, encode(np.arange(12, dtype="f4").reshape(3, 4), "npy")
        ),
        file_format="npy",
        spec=specification(),
        cancel=lambda: None,
    )
    loaded = restored(runtime, save(runtime, source, service, "original", "a"), service)
    selected, _ = filter_valid(
        runtime,
        loaded,
        FilterCloudValid(finite_fields=("positions",), sentinels=()),
        cancel=lambda: None,
    )
    used = runtime.budget.used

    def cancel():
        if failure == "cancel":
            raise InterruptedError("cancel save")

    with pytest.raises((InterruptedError, InvalidRequestError)):
        save_cloud(
            runtime,
            selected,
            service=service,
            project_id="other" if failure == "project" else "test",
            name="fail",
            mode="derived",
            write_identity="b" * 64,
            policy=replace(POLICY, max_asset_bytes=128, chunk_bytes=64)
            if failure == "budget"
            else POLICY,
            cancel=cancel,
        )
    assert len(service.list_versions(project_id="test")) == 1
    assert service.list_versions(project_id="other") == []
    assert runtime.budget.used == used
    compare(
        runtime,
        selected,
        restored(runtime, save(runtime, selected, service, "derived", "c"), service),
    )


@pytest.mark.parametrize("entry", ["file", "array"])
def test_conversion_cancel_does_not_keep_input_via_error_traceback(
    context, arena_input, monkeypatch, entry
):
    """错误对象仍留给日志持有时，也不能通过已退栈帧固定原输入。"""
    from custom_nodes.metrology3d_nodes.shared.io import read_raster

    runtime, service = context
    arena, receipt, acquire = arena_input
    original = read_raster.convert_raster
    refs = []

    def interrupted(samples, mask, spec, **kwargs):
        refs.append(weakref.ref(samples))
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise InterruptedError("conversion cancelled")

        return original(samples, mask, spec, **(kwargs | {"cancel": cancel}))

    monkeypatch.setattr(read_raster, "convert_raster", interrupted)
    with pytest.raises(InterruptedError) as held_error:
        if entry == "file":
            read_raster.read_raster_reference(
                runtime=runtime,
                object_store=service.storage,
                project_id="test",
                file=publish(
                    service.storage, encode(np.ones((3, 4), dtype="f4"), "npy")
                ),
                file_format="npy",
                spec=specification(),
                cancel=lambda: None,
            )
        else:
            read_raster.read_raster_local(
                runtime=runtime,
                descriptor=descriptor(),
                expected_descriptor_sha256=raster_descriptor_sha256(descriptor()),
                acquire_view=acquire,
                cancel=lambda: None,
            )
    assert held_error.value and refs and all(r() is None for r in refs)
    assert runtime.budget.used == 0
    assert arena.request_reclaim(receipt) == "released"
