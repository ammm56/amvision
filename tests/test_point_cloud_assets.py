"""点云 v2 资产的严格布局、原子提交、幂等及取消边界。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceContent,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
    ResourceConflictError,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CloudAssetPolicy,
    cloud_blob_key,
)
from tests.point_cloud_support import spatial, create_resource_service

service = pytest.fixture(name="service")(create_resource_service)


def asset_content(data=b"\0" * 24):
    """独立构造已知二进制布局，测试预算不写入生产。"""
    count = len(data) // 12
    return MeasurementResourceContent(
        kind="point-cloud",
        point_cloud={
            "format_id": "amvision.point-cloud-asset.v1",
            "kind": "point-cloud",
            "representation": "array-blocks",
            "source": {
                "kind": "local-array",
                "content_sha256": sha256(data).hexdigest(),
                "descriptor_sha256": "2" * 64,
                "source_observation_id": None,
            },
            "spatial": spatial(),
            "provenance": {"method": None, "parents": [], "source_retained": True},
            "blobs": [
                {
                    "role": "data",
                    "name": "data.bin",
                    "content_length": len(data),
                    "sha256": sha256(data).hexdigest(),
                }
            ],
            "source_field_names": [],
            "parent_assets": [],
            "point_count": count,
            "source_metadata": None,
            "fields": [
                {
                    "name": "positions",
                    "semantic": "position",
                    "dtype": "float32",
                    "components": 3,
                    "unit": None,
                    "count": count,
                    "offset_bytes": 0,
                    "byte_length": len(data),
                }
            ],
            "content_length": len(data),
            "indices": None,
            "lineage": None,
            "vertex_kind": "source",
            "topology": None,
        },
    )


POLICY = CloudAssetPolicy(max_asset_bytes=4096, max_archive_bytes=16384, chunk_bytes=7)


def save(service, *, data=b"\0" * 24, content=None, identity="a" * 64, **kwargs):
    """经真实 ObjectStore 保存，不假定 write 返回即成功。"""
    return service.save_cloud(
        project_id="test",
        name="Cloud",
        content=content or asset_content(data),
        streams={"data.bin": BytesIO(data)},
        write_identity=identity,
        policy=POLICY,
        cancel=kwargs.pop("cancel", lambda: None),
        **kwargs,
    )


@pytest.mark.parametrize("data", [b"\0" * 24, b""])
def test_save_read_replay_and_delete(service, data):
    """空派生内容和普通内容均完整提交，重入不产生第二个版本。"""
    doc = save(service, data=data)
    assert service.read(doc.reference, project_id="test") == doc
    assert save(service, data=data) == doc
    service.verify_cloud(doc, policy=POLICY, cancel=lambda: None)
    assert len(service.list_versions(project_id="test")) == 1
    service.delete(doc.reference, project_id="test")
    assert not service.storage.resolve(
        cloud_blob_key(service, doc.reference, doc.content.point_cloud.blobs[0])
    ).exists()
    with pytest.raises(ResourceConflictError):
        save(service, data=data)


def test_version_conflict_and_same_identity_changed_content(service):
    """不同提交不能覆盖同一基版本，同次调用也不能换内容。"""
    doc = save(service)
    with pytest.raises(ResourceConflictError):
        save(service, data=b"1" * 24)
    second = save(service, expected_base=doc.reference, identity="b" * 64)
    assert second.reference.version == 2
    assert save(service, expected_base=doc.reference, identity="b" * 64) == second
    with pytest.raises(ResourceConflictError):
        save(service, expected_base=doc.reference, identity="c" * 64)


@pytest.mark.parametrize("data", [b"short", b"1" * 24, b"\0" * 25])
def test_invalid_stream_never_commits(service, data):
    """短流、坏摘要和额外字节不能发布版本。"""
    with pytest.raises(InvalidRequestError):
        save(service, data=data, content=asset_content())
    assert service.list_versions(project_id="test") == []
    assert not list(service.storage.resolve(service.root("test")).rglob("content.bin"))
    assert save(service).reference.version == 1


@pytest.mark.parametrize("data", [b"short", b"1" * 24, b"\0" * 25])
def test_replay_still_validates_the_submitted_stream(service, data):
    """幂等仅避免重复副作用，不能让同一 manifest 的损坏重传变成成功。"""
    document = save(service)
    with pytest.raises(InvalidRequestError):
        save(service, data=data, content=asset_content())
    assert service.read(document.reference, project_id="test") == document
    service.verify_cloud(document, policy=POLICY, cancel=lambda: None)


def test_cancellation_before_commit_and_after_commit(service, monkeypatch):
    """提交前清理；原子提交后报告异常也不能破坏已落地副作用。"""
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("cancel")

    with pytest.raises(RuntimeError, match="cancel"):
        save(service, cancel=cancel)
    assert service.list_versions(project_id="test") == []
    write = service.storage.write_json

    def committed_then_error(key, value):
        write(key, value)
        raise RuntimeError("after commit")

    monkeypatch.setattr(service.storage, "write_json", committed_then_error)
    with pytest.raises(RuntimeError, match="after commit"):
        save(service)
    doc = save(service)
    service.verify_cloud(doc, policy=POLICY, cancel=lambda: None)


def _interrupted_writer(root, committed):
    """真实子进程在指定提交边界停住，父进程负责终止及确认退出。"""
    from pathlib import Path
    from time import sleep

    service = create_resource_service(Path(root))
    method = "write_json" if committed else "write_immutable_stream"
    original = getattr(service.storage, method)

    def pause_after_write(*args, **kwargs):
        result = original(*args, **kwargs)
        (Path(root) / "writer-reached").write_bytes(b"ready")
        sleep(30)
        return result

    setattr(service.storage, method, pause_after_write)
    save(service)


@pytest.mark.parametrize("committed", [False, True])
def test_process_exit_before_and_after_commit(service, tmp_path, committed):
    """强杀释放真实项目锁；未提交可重试，已提交副作用不丢失或重复。"""
    import multiprocessing
    from time import monotonic, sleep

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_interrupted_writer, args=(str(tmp_path), committed)
    )
    process.start()
    try:
        deadline = monotonic() + 20
        reached = tmp_path / "writer-reached"
        while not reached.exists() and process.is_alive() and monotonic() < deadline:
            sleep(0.01)
        assert reached.exists(), "writer did not reach the requested boundary"
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        assert len(service.list_versions(project_id="test")) == int(committed)
        document = save(service)
        assert document.reference.version == 1
        assert len(service.list_versions(project_id="test")) == 1
        service.verify_cloud(document, policy=POLICY, cancel=lambda: None)
    finally:
        if process.is_alive():
            process.kill()
            process.join(10)
        assert not process.is_alive()
        process.close()


def test_storage_failure_removes_uncommitted_data(service, monkeypatch):
    """数据落盘后发生磁盘错误，不发布半个资源且允许明确重试。"""
    import errno

    original = service.storage.write_immutable_stream

    def disk_full(**kwargs):
        original(**kwargs)
        raise OSError(errno.ENOSPC, "test disk full")

    with monkeypatch.context() as patch:
        patch.setattr(service.storage, "write_immutable_stream", disk_full)
        with pytest.raises(PersistenceOperationError) as error:
            save(service)
        assert error.value.details["errno"] == errno.ENOSPC
    assert service.list_versions(project_id="test") == []
    assert not list(service.storage.resolve(service.root("test")).rglob("content.bin"))
    assert save(service).reference.version == 1


def test_read_detects_corrupt_data_not_just_metadata(service):
    """等长篡改即使存储 manifest 未变也必须被读回检查发现。"""
    doc = save(service)
    path = service.storage.resolve(
        cloud_blob_key(service, doc.reference, doc.content.point_cloud.blobs[0])
    )
    path.write_bytes(b"X" * 24)
    with pytest.raises(InvalidRequestError):
        service.verify_cloud(doc, policy=POLICY, cancel=lambda: None)


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["point_cloud"]["fields"][0].update(offset_bytes=1),
        lambda c: c["point_cloud"]["blobs"][0].update(name="../data.bin"),
        lambda c: c["point_cloud"].update(content_length=25),
        lambda c: c["point_cloud"].update(parent_assets=[{"kind": "point-cloud"}]),
        lambda c: c["point_cloud"].update(
            indices={
                "dtype": "uint32",
                "count": 2,
                "source_point_count": 2,
                "source": {"kind": "derived"},
            }
        ),
        lambda c: c["point_cloud"]["provenance"].update(
            method={"method_id": "unknown"}
        ),
    ],
)
def test_bad_asset_schema(change):
    """未知方法、无效布局、虚假索引与父引用在写入前拒绝。"""
    content = deepcopy(asset_content().model_dump(mode="json"))
    change(content)
    with pytest.raises(ValueError):
        MeasurementResourceContent.model_validate(content)


def test_stream_archive_roundtrip_and_budget(service):
    """资产包流式往返，跨项目建立新身份且保留内容摘要。"""
    doc = save(service)
    output = BytesIO()
    size = service.export_cloud_archive(
        doc.reference,
        project_id="test",
        stream=output,
        policy=POLICY,
        cancel=lambda: None,
    )
    assert size == len(output.getvalue())
    imported = service.import_cloud_archive(
        stream=output,
        project_id="other",
        name="Imported",
        write_identity="c" * 64,
        policy=POLICY,
        cancel=lambda: None,
    )
    assert imported.reference.sha256 == doc.reference.sha256
    service.verify_cloud(imported, policy=POLICY, cancel=lambda: None)
    with pytest.raises(InvalidRequestError, match="限额"):
        service.export_cloud_archive(
            doc.reference,
            project_id="test",
            stream=BytesIO(),
            policy=CloudAssetPolicy(
                max_asset_bytes=4096, max_archive_bytes=64, chunk_bytes=7
            ),
            cancel=lambda: None,
        )


@pytest.mark.parametrize(
    "variant", ["extra", "missing", "duplicate", "compressed", "truncated", "bad-data"]
)
def test_bad_archives_never_commit(service, variant):
    """包的成员、压缩和数据损坏不能通过仅有 manifest 的检查。"""
    output = BytesIO()
    content = asset_content()
    with ZipFile(
        output, "w", compression=ZIP_DEFLATED if variant == "compressed" else 0
    ) as archive:
        archive.writestr("resource.json", content.model_dump_json())
        if variant != "missing":
            archive.writestr(
                "data.bin", b"X" * 24 if variant == "bad-data" else b"\0" * 24
            )
        if variant == "extra":
            archive.writestr("../outside", b"")
        if variant == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("data.bin", b"\0" * 24)
    if variant == "truncated":
        output = BytesIO(output.getvalue()[:-8])
    with pytest.raises(InvalidRequestError):
        service.import_cloud_archive(
            stream=output,
            project_id="test",
            name="Bad",
            write_identity="b" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
    assert service.list_versions(project_id="test") == []


def test_runtime_save_filter_restore_exact_fields_and_indices(service):
    """实际运行来源保存/过滤/重读，保留 uint64、NaN 位模式和源行号。"""
    import numpy as np
    from tests.test_metrology3d_preprocess import make_cloud
    from tests.point_cloud_support import policy as io_policy
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
    from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
    from custom_nodes._metrology3d_nodes.shared.cloud_assets import (
        save_cloud,
        read_asset,
    )

    scope, runtime, source = make_cloud(
        unit=None,
        coordinates=np.array([[1, 2, 3], [np.nan, 2, 3], [7, 8, 9]], dtype="<f4"),
        attributes=[("serial", np.array([2**64 - 1, 2**63 + 1, 7], dtype="<u8"), None)],
    )
    asset_policy = CloudAssetPolicy(
        max_asset_bytes=8192, max_archive_bytes=16384, chunk_bytes=128
    )
    other = ResourceScope(kind="test")
    target = get_cloud_runtime(other, run_id="restored", policy=io_policy())
    try:
        original = save_cloud(
            runtime,
            source,
            service=service,
            project_id="test",
            name="Original",
            mode="original",
            write_identity="d" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
        result, summary = filter_valid(
            runtime,
            source,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        derived = save_cloud(
            runtime,
            result,
            service=service,
            project_id="test",
            name="Filtered",
            mode="derived",
            write_identity="e" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
        assert summary["removed_count"] == 1
        restored = read_asset(
            target,
            derived,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        assert (
            restored.run_id != result.run_id
            and restored.observation_id != result.observation_id
        )
        with target.borrow(restored) as view:
            np.testing.assert_array_equal(view.source_indices(0, 2), [0, 2])
            np.testing.assert_array_equal(
                view.chunk(0, 2)["serial"].ravel(),
                np.array([2**64 - 1, 7], dtype="<u8"),
            )
        original_ref = read_asset(
            target,
            original,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        with target.borrow(original_ref) as view, runtime.borrow(source) as src:
            assert (
                view.chunk(0, 2)["positions"].tobytes()
                == src.chunk(0, 2)["positions"].tobytes()
            )
        assert restored.spatial.length_unit is None
    finally:
        assert not scope.close()
        assert not other.close()
        assert runtime.budget.used == target.budget.used == 0


def test_parent_delete_protection_and_original_recovery(service):
    """持久派生链保留真实父引用，删除保护与原件恢复复用同一版本服务。"""
    from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
    from backend.service.application.errors import ResourceInUseError
    from tests.test_metrology3d_preprocess import make_cloud
    from custom_nodes._metrology3d_nodes.shared.cloud_assets import (
        save_cloud,
        read_asset,
    )
    from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid

    limits = CloudAssetPolicy(
        max_asset_bytes=8192, max_archive_bytes=16384, chunk_bytes=128
    )
    scope, runtime, source = make_cloud()

    def persist(cloud, mode, identity):
        return save_cloud(
            runtime,
            cloud,
            service=service,
            project_id="test",
            name="Saved",
            mode=mode,
            write_identity=identity * 64,
            policy=limits,
            cancel=lambda: None,
        )

    try:
        original = persist(source, "original", "1")
        restored = read_asset(
            runtime,
            original,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        filtered, _ = filter_valid(
            runtime,
            restored,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        child = persist(filtered, "derived", "2")
        assert service.read(
            child, project_id="test"
        ).content.point_cloud.provenance.source_retained
        with pytest.raises(ResourceInUseError):
            service.delete(original, project_id="test")
        child_ref = read_asset(
            runtime,
            child,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        copied = persist(child_ref, "original", "3")
        assert copied.sha256 == original.sha256
        service.delete(child, project_id="test")
        service.delete(original, project_id="test")
    finally:
        assert not scope.close()


def test_resource_collection_and_prepare_remain_metadata_only(service):
    """固定节点资产引用参与发布/删除检查，准备层不缓存整云数组。"""
    from types import SimpleNamespace
    from backend.service.application.workflows.documents.measurement_resources import (
        collect_measurement_references,
        PreparedMeasurementResources,
    )
    from backend.service.application.errors import ServiceConfigurationError

    doc = save(service)
    template = SimpleNamespace(
        nodes=[
            SimpleNamespace(
                node_type_id="custom.metrology3d.read-cloud",
                node_id="read",
                parameters={
                    "source": {"kind": "asset", "reference": doc.reference.model_dump()}
                },
            )
        ]
    )
    assert collect_measurement_references(template) == (doc.reference,)
    with pytest.raises(ServiceConfigurationError, match="预算"):
        service.validate_template(template, project_id="test")
    cache = PreparedMeasurementResources(service.storage)
    result = cache.prepare((doc.reference,), project_id="test")
    assert result[doc.reference.model_dump_json()]["reference"] == doc.reference
    assert cache.entries == {} and cache.bytes == 0
