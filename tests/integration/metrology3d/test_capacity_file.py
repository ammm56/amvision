"""完整容量文件经过真实 Preview 暂存、解码、资产往返和交换导出。"""

import numpy as np
import pytest

from backend.contracts.workflows.preview_session import PREVIEW_CHUNK_SIZE
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.preview.buffers import (
    PreviewBuffers,
    PreviewMemoryError,
)
from backend.service.application.workflows.preview.inputs import PreviewInputStore
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes.metrology3d_nodes.shared.io.export_file import (
    CloudExportOptions,
    export_cloud_file,
)
from custom_nodes.metrology3d_nodes.shared.io.formats import inspect_cloud_file
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from tests.point_cloud_support import create_resource_service
from tests.test_metrology3d_crop import box, parameters
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from tests.integration.metrology3d.capacity_support import (
    ROWS,
    assert_cloud,
    read_options,
    records,
    report,
    settings,
    stage,
    write_ply,
)


def test_file_capacity_roundtrip(tmp_path, request):
    """默认小样本；显式 --cloud-capacity-bytes=1000000000 执行 1 GB 验收。"""
    size = request.config.getoption("--cloud-capacity-bytes")
    policy = settings().workflow_runtime.point_cloud
    service = create_resource_service(tmp_path)
    upload_root = tmp_path / "uploads"
    buffers = PreviewBuffers(file_policy=policy.preview_files, file_root=upload_root)
    buffers.register_owner("capacity")
    store = PreviewInputStore(service.storage, "test", "capacity")
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="capacity", policy=policy.io)
    restored_scope = ResourceScope(kind="test")
    restored_runtime = get_cloud_runtime(
        restored_scope, run_id="restored", policy=policy.io
    )
    subset_scope = ResourceScope(kind="test")
    subset_runtime = get_cloud_runtime(subset_scope, run_id="subset", policy=policy.io)
    pinned = None
    with report(request, "file") as evidence:
        try:
            source = tmp_path / "input.ply"
            with stage(evidence, "generate"):
                count = write_ply(source, size)
            evidence["point_count"] = count
            with stage(evidence, "upload"):
                blob = buffers.allocate_file(
                    "capacity",
                    size,
                    media_type="application/octet-stream",
                    file_name="input.ply",
                )
                with source.open("rb") as stream:
                    index = 0
                    while block := stream.read(PREVIEW_CHUNK_SIZE):
                        buffers.write_chunk("capacity", blob, index, block)
                        index += 1
                buffers.commit("capacity", blob)
                descriptor = buffers.pin_descriptor("capacity", blob)
                pinned = blob
                file = store.register_snapshot(descriptor)
                buffers.release("capacity", blob)
            with stage(evidence, "decode"):
                cloud = read_file_reference(
                    runtime=runtime,
                    object_store=store,
                    project_id="test",
                    file=file,
                    options=read_options(),
                    cancel=lambda: None,
                )
                assert runtime.budget.used == count * 16
            with stage(evidence, "check_all_fields"):
                assert_cloud(runtime, cloud, count)
            with stage(evidence, "save"):
                saved = save_cloud(
                    runtime,
                    cloud,
                    service=service,
                    project_id="test",
                    name="Capacity",
                    mode="derived",
                    write_identity="c" * 64,
                    policy=policy.assets(),
                    cancel=lambda: None,
                )
            with stage(evidence, "archive_export_import"):
                with (tmp_path / "asset.zip").open("w+b") as stream:
                    evidence["archive_bytes"] = service.export_cloud_archive(
                        saved,
                        project_id="test",
                        stream=stream,
                        policy=policy.assets(),
                        cancel=lambda: None,
                    )
                    imported = service.import_cloud_archive(
                        stream=stream,
                        project_id="other",
                        name="Restored",
                        write_identity="d" * 64,
                        policy=policy.assets(),
                        cancel=lambda: None,
                    )
            with stage(evidence, "restore"):
                restored = read_asset(
                    restored_runtime,
                    imported.reference,
                    service=service,
                    project_id="other",
                    policy=policy.assets(),
                    cancel=lambda: None,
                )
                assert_cloud(restored_runtime, restored, count)
            with stage(evidence, "exchange_export_read"):
                with (tmp_path / "exchange.ply").open("w+b") as stream:
                    summary, opts = export_cloud_file(
                        runtime,
                        cloud,
                        CloudExportOptions(
                            profile_id="ply-binary-le",
                            profile_version=1,
                            fields=("positions", "serial"),
                            file_name="exchange.ply",
                            spatial_acknowledged=True,
                        ),
                        stream=stream,
                        max_output_bytes=policy.max_export_bytes,
                        cancel=lambda: None,
                    )
                    assert summary["fields_omitted"] == []
                    evidence["exchange_bytes"] = stream.tell()
                    stream.seek(0)
                    data = inspect_cloud_file(
                        stream, opts, policy.io, lambda: None
                    ).read()
                    assert len(data) == count
                    for start in range(0, count, ROWS):
                        stop = min(start + ROWS, count)
                        expected = records(start, stop)
                        for name in expected.dtype.names:
                            np.testing.assert_array_equal(
                                data[name][start:stop], expected[name]
                            )
                    del data
            with stage(evidence, "crop_save_restore"):
                assert not restored_scope.close()
                subset, _ = crop_roi(
                    runtime,
                    cloud,
                    parameters(
                        box(
                            center=[255.5, 2047.5, 0.25],
                            size=[511, 4095, 1],
                        )
                    ),
                    cancel=lambda: None,
                )
                kept = (count // 1024) * 512 + min(count % 1024, 512)
                assert subset.point_count == kept
                saved_subset = save_cloud(
                    runtime,
                    subset,
                    service=service,
                    project_id="test",
                    name="Subset",
                    mode="derived",
                    write_identity="e" * 64,
                    policy=policy.assets(),
                    cancel=lambda: None,
                )
                recovered = read_asset(
                    subset_runtime,
                    saved_subset,
                    service=service,
                    project_id="test",
                    policy=policy.assets(),
                    cancel=lambda: None,
                )
                assert recovered.point_count == kept
                assert subset_runtime.source_point_count(recovered) == count
                with subset_runtime.borrow(recovered) as view:
                    for start in range(0, kept, ROWS):
                        logical = np.arange(
                            start, min(start + ROWS, kept), dtype=np.uint32
                        )
                        original = (logical // 512) * 1024 + logical % 512
                        block = view.chunk(start, start + len(logical))
                        np.testing.assert_array_equal(
                            view.source_indices(start, start + len(logical)), original
                        )
                        np.testing.assert_array_equal(
                            block["serial"].reshape(-1), original
                        )
                        np.testing.assert_array_equal(
                            block["positions"][:, 0], original % 1024
                        )
                        np.testing.assert_array_equal(
                            block["positions"][:, 1], (original // 1024) % 4096
                        )
                        np.testing.assert_array_equal(
                            block["positions"][:, 2], np.full(len(logical), 0.25)
                        )
                    block = None
                evidence["derived_point_count"] = kept
            with pytest.raises(PreviewMemoryError, match="length_invalid"):
                buffers.allocate_file(
                    "capacity",
                    1000000001,
                    media_type="application/octet-stream",
                    file_name="too-big.ply",
                )
        finally:
            assert not scope.close()
            assert not restored_scope.close()
            assert not subset_scope.close()
            store.clear()
            if pinned is not None:
                buffers.unpin("capacity", pinned)
            buffers.release_owner("capacity")
            buffers.close()
        assert (
            runtime.budget.used
            == restored_runtime.budget.used
            == subset_runtime.budget.used
            == 0
        )
        assert not list(upload_root.glob("**/*"))
        evidence["live_array_bytes_after_close"] = 0
        evidence["temporary_inputs_after_close"] = 0


def test_incomplete_upload_and_cancelled_read(tmp_path):
    """未传完/取消后的文件和解码预算均释放，不能残留已登记输入。"""
    from concurrent.futures import CancelledError

    policy = settings().workflow_runtime.point_cloud
    service = create_resource_service(tmp_path)
    root = tmp_path / "uploads"
    buffers = PreviewBuffers(file_policy=policy.preview_files, file_root=root)
    buffers.register_owner("cancel")
    store = PreviewInputStore(service.storage, "test", "cancel")
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="cancel", policy=policy.io)
    try:
        blob = buffers.allocate_file(
            "cancel",
            4096,
            media_type="application/octet-stream",
            file_name="cancel.ply",
        )
        buffers.write_chunk("cancel", blob, 0, b"incomplete")
        with pytest.raises(PreviewMemoryError, match="incomplete"):
            buffers.commit("cancel", blob)
        buffers.release("cancel", blob)
        with pytest.raises(CancelledError):
            read_file_reference(
                runtime=runtime,
                object_store=store,
                project_id="test",
                file={},
                options=read_options(),
                cancel=lambda: (_ for _ in ()).throw(CancelledError()),
            )
    finally:
        assert not scope.close()
        store.clear()
        buffers.release_owner("cancel")
        buffers.close()
    assert runtime.budget.used == 0
    assert not list(root.glob("**/*"))
