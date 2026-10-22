"""完整 ASCII PLY 经 ObjectStore、运行引用、索引过滤和真实 mmap 的验收。"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import platform
from time import perf_counter, monotonic_ns

import numpy as np

from backend.contracts.workflows.point_cloud import (
    MAX_POINT_CLOUD_INPUT_BYTES,
    CloudFileOptions,
    CloudBufferDescriptor,
)
from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.point_cloud.local_array import (
    cloud_descriptor_sha256,
)
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    MmapBufferArena,
    MmapBufferArenaConfig,
    MmapBufferArenaExternalAccess,
)
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes._metrology3d_nodes.shared.io.export_file import (
    CloudExportOptions,
    export_cloud_file,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CloudAssetPolicy,
)


def _verify_cloud(runtime, reference, expected_sha256):
    """完整逐块校验数据及源索引，不抽取样本前缀。"""
    digest = sha256()
    with runtime.borrow(reference) as view:
        for start in range(0, reference.point_count, runtime.policy.chunk_rows):
            stop = min(start + runtime.policy.chunk_rows, reference.point_count)
            block = view.chunk(start, stop)
            with memoryview(block["positions"]).cast("B") as data:
                digest.update(data)
            np.testing.assert_array_equal(
                view.source_indices(start, stop), np.arange(start, stop, dtype="uint32")
            )
        block = None
    if digest.hexdigest() != expected_sha256:
        raise ValueError("完整规范数组与独立期望摘要不一致")
    return digest.hexdigest()


def _verify_assets(runtime, source, filtered, storage, args):
    """完整原件、派生资产、归档导入和新运行重读；所有样本点参加校验。"""
    service = MeasurementResourceService(storage)
    policy = CloudAssetPolicy(
        max_asset_bytes=args.asset_max_bytes,
        max_archive_bytes=args.asset_archive_max_bytes,
        chunk_bytes=runtime.policy.chunk_bytes,
    )
    results = {}
    for mode, cloud in (("original", source), ("derived", filtered)):
        reference = save_cloud(
            runtime,
            cloud,
            service=service,
            project_id="sample",
            name=f"Sample {mode}",
            mode=mode,
            write_identity=sha256(mode.encode()).hexdigest(),
            policy=policy,
            cancel=lambda: None,
        )
        archive_path = args.work_dir / f"{mode}.zip"
        with archive_path.open("wb") as stream:
            archive_bytes = service.export_cloud_archive(
                reference,
                project_id="sample",
                stream=stream,
                policy=policy,
                cancel=lambda: None,
            )
        with archive_path.open("rb") as stream:
            imported = service.import_cloud_archive(
                stream=stream,
                project_id="imported",
                name=f"Imported {mode}",
                write_identity=sha256(mode.encode()).hexdigest(),
                policy=policy,
                cancel=lambda: None,
            )
        if imported.reference.sha256 != reference.sha256:
            raise ValueError("跨项目资产归档内容摘要改变")
        isolated = ResourceScope(kind="workflow")
        restored_runtime = get_cloud_runtime(
            isolated, run_id=f"restored-{mode}", policy=runtime.policy
        )
        try:
            restored = read_asset(
                restored_runtime,
                imported.reference,
                service=service,
                project_id="imported",
                policy=policy,
                cancel=lambda: None,
            )
            digest = _verify_cloud(
                restored_runtime, restored, args.expected_array_sha256
            )
            if restored.spatial != source.spatial or restored.fields != source.fields:
                raise ValueError("资产读取改变字段或空间声明")
        finally:
            if isolated.close() or restored_runtime.budget.used != 0:
                raise RuntimeError("资产恢复作用域没有完整释放")
        results[mode] = {
            "content_sha256": reference.sha256,
            "archive_bytes": archive_bytes,
            "array_sha256": digest,
            "point_count": restored.point_count,
            "budget_after_close": restored_runtime.budget.used,
        }
        service.delete(imported.reference, project_id="imported")
        service.delete(reference, project_id="sample")
        archive_path.unlink()
    return results


def _verify_exchange(runtime, source, storage, args):
    """全部点经三种交换文件导出并严格读回，不用近似数值判等。"""
    results = {}
    for profile in ("ply-binary-le", "pcd-binary", "xyz-whitespace"):
        file = args.work_dir / f"{profile}.bin"
        parameters = CloudExportOptions(
            profile_id=profile,
            profile_version=1,
            fields=("positions",),
            file_name="exchange.bin",
            spatial_acknowledged=True,
        )
        with file.open("wb") as stream:
            summary, opts = export_cloud_file(
                runtime,
                source,
                parameters,
                stream=stream,
                max_output_bytes=args.asset_max_bytes,
                cancel=lambda: None,
            )
        with file.open("rb") as stream:
            metadata = storage.write_immutable_stream(
                object_prefix=f"projects/sample/results/{profile}",
                source_stream=stream,
                media_type="application/octet-stream",
                extension="bin",
                chunk_size=runtime.policy.chunk_bytes,
                max_bytes=args.asset_max_bytes,
            ).metadata
        payload = {
            "transport_kind": "storage",
            "storage_ref": "object-store",
            "object_key": metadata.object_key,
            "file_name": "exchange.bin",
            "media_type": metadata.media_type,
            "content_length": metadata.content_length,
            "checksum_algorithm": "sha256",
            "checksum": metadata.checksum,
            "immutable_version": metadata.immutable_version,
        }
        scope = ResourceScope(kind="workflow")
        restored_runtime = get_cloud_runtime(
            scope, run_id=f"exchange-{profile}", policy=runtime.policy
        )
        try:
            restored = read_file_reference(
                runtime=restored_runtime,
                object_store=storage,
                project_id="sample",
                file=payload,
                options=opts,
                cancel=lambda: None,
            )
            digest = _verify_cloud(
                restored_runtime, restored, args.expected_array_sha256
            )
        finally:
            if scope.close() or restored_runtime.budget.used:
                raise RuntimeError("交换文件重读没有完整释放")
        results[profile] = {
            "file_bytes": metadata.content_length,
            "file_sha256": metadata.checksum,
            "array_sha256": digest,
            "point_count": restored.point_count,
            "fields_omitted": summary["fields_omitted"],
            "budget_after_close": restored_runtime.budget.used,
        }
        storage.delete_tree(f"projects/sample/results/{profile}")
        file.unlink()
    return results


def main():
    """全部预算显式提供，工作目录必须是新目录；报告不含本机源路径。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-array-sha256", required=True)
    parser.add_argument("--expected-points", type=int, required=True)
    parser.add_argument("--array-lease-seconds", type=float, required=True)
    parser.add_argument("--arena-min-block-bytes", type=int, required=True)
    parser.add_argument("--arena-reader-slots", type=int, required=True)
    parser.add_argument("--arena-revocation-grace-seconds", type=float, required=True)
    parser.add_argument("--asset-max-bytes", type=int, required=True)
    parser.add_argument("--asset-archive-max-bytes", type=int, required=True)
    parser.add_argument("--verify-exchange", action="store_true")
    parser.add_argument("--verify-nodes-policy", type=Path)
    parser.add_argument("--node-preview-points", type=int)
    for name in (
        "max_header_bytes",
        "max_decoded_bytes",
        "max_working_bytes",
        "chunk_rows",
        "chunk_bytes",
        "max_live_array_bytes",
    ):
        parser.add_argument("--" + name.replace("_", "-"), type=int, required=True)
    args = parser.parse_args()
    policy = PointCloudIoPolicy(
        **{name: getattr(args, name) for name in PointCloudIoPolicy.model_fields}
    )
    args.work_dir.mkdir(parents=True, exist_ok=False)
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(args.work_dir)))
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="full-sample", policy=policy)
    opts = CloudFileOptions.model_validate(
        {
            "profile_id": "ply-ascii",
            "profile_version": 1,
            "spatial": {
                "length_unit": None,
                "unit_source": "unknown",
                "frame_id": "sample-source",
                "axes": {
                    "handedness": "unknown",
                    "axis_labels": ["X", "Y", "Z"],
                    "definition_source": "unknown",
                },
            },
            "field_mapping": [
                {
                    "source_names": ["x", "y", "z"],
                    "target_name": "positions",
                    "semantic": "position",
                    "dtype": "float32",
                    "components": 3,
                    "unit": None,
                }
            ],
        }
    )
    with args.sample.open("rb") as stream:
        metadata = storage.write_immutable_stream(
            object_prefix="projects/sample/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
            chunk_size=policy.chunk_bytes,
            max_bytes=MAX_POINT_CLOUD_INPUT_BYTES,
        ).metadata
    if metadata.checksum != args.expected_sha256:
        raise ValueError("原始样本 SHA-256 不匹配")
    payload = {
        "transport_kind": "storage",
        "storage_ref": "object-store",
        "object_key": metadata.object_key,
        "file_name": "sample.ply",
        "media_type": metadata.media_type,
        "content_length": metadata.content_length,
        "checksum_algorithm": "sha256",
        "checksum": metadata.checksum,
        "immutable_version": metadata.immutable_version,
    }
    started = perf_counter()
    try:
        result = read_file_reference(
            runtime=runtime,
            object_store=storage,
            project_id="sample",
            file=payload,
            options=opts,
            cancel=lambda: None,
        )
        elapsed = perf_counter() - started
        if result.point_count != args.expected_points:
            raise ValueError("点数与独立期望不一致")
        array_digest = _verify_cloud(runtime, result, args.expected_array_sha256)
        parameters = FilterCloudValid(finite_fields=("positions",), sentinels=())
        filtered, summary = filter_valid(
            runtime, result, parameters, cancel=lambda: None
        )
        _verify_cloud(runtime, filtered, args.expected_array_sha256)
        if runtime.original_source(filtered) != (result, opts):
            raise ValueError("派生点云丢失原始文件身份或读取参数")
        asset_results = _verify_assets(runtime, result, filtered, storage, args)
        exchange_results = (
            _verify_exchange(runtime, result, storage, args)
            if args.verify_exchange
            else None
        )
        node_results = None
        if args.verify_nodes_policy is not None:
            from backend.service.application.workflows.point_cloud.execution_policy import (
                PointCloudExecutionPolicy,
            )
            from scripts.metrology3d_node_check import verify_node_graph

            node_policy = PointCloudExecutionPolicy.model_validate_json(
                args.verify_nodes_policy.read_text(encoding="utf-8")
            )
            if node_policy.io != policy or args.node_preview_points is None:
                raise ValueError("节点验收必须显式提供相同 I/O 策略和显示点数")
            node_results = verify_node_graph(
                storage=storage,
                file=payload,
                options=opts,
                policy=node_policy,
                point_limit=args.node_preview_points,
                expected_points=args.expected_points,
                expected_array_sha256=args.expected_array_sha256,
            )
        array_bytes = result.point_count * 12
        arena_capacity = (
            1 << (max(array_bytes, args.arena_min_block_bytes) - 1).bit_length()
        )
        arena_config = MmapBufferArenaConfig(
            root_dir=args.work_dir / "arena",
            arena_id="full-sample-array",
            arena_size_bytes=arena_capacity,
            min_block_size_bytes=args.arena_min_block_bytes,
            max_allocation_bytes=arena_capacity,
            reader_guard_slots=args.arena_reader_slots,
            revocation_grace_seconds=args.arena_revocation_grace_seconds,
        )
        with ExitStack() as resources:
            arena = resources.enter_context(MmapBufferArena(arena_config))
            external = MmapBufferArenaExternalAccess(arena_config)
            resources.callback(external.close)
            resources.callback(scope.close)
            receipt = arena.allocate(
                content_length=array_bytes,
                deadline_ns=monotonic_ns()
                + int(args.array_lease_seconds * 1_000_000_000),
            )
            with (
                arena.acquire_writer_view(receipt) as writable,
                runtime.borrow(result) as view,
            ):
                for start in range(0, result.point_count, policy.chunk_rows):
                    stop = min(start + policy.chunk_rows, result.point_count)
                    with memoryview(view.chunk(start, stop)["positions"]).cast(
                        "B"
                    ) as data:
                        writable[start * 12 : stop * 12] = data
            arena.publish_active(receipt)
            descriptor = CloudBufferDescriptor.model_validate(
                {
                    "format_id": "amvision.point-cloud-buffer.v1",
                    "point_count": result.point_count,
                    "content_length": array_bytes,
                    "spatial": opts.spatial,
                    "fields": [
                        {
                            **result.fields[0].model_dump(),
                            "count": result.point_count,
                            "offset_bytes": 0,
                            "byte_length": array_bytes,
                        }
                    ],
                }
            )
            local = runtime.open_local(
                descriptor=descriptor,
                expected_descriptor_sha256=cloud_descriptor_sha256(descriptor),
                acquire_view=lambda: external.acquire_reader_view(receipt),
                cancel=lambda: None,
            )
            _verify_cloud(runtime, local, args.expected_array_sha256)
            local_filtered, local_summary = filter_valid(
                runtime, local, parameters, cancel=lambda: None
            )
            _verify_cloud(runtime, local_filtered, args.expected_array_sha256)
            if local_summary != summary or arena.request_reclaim(receipt) != "revoking":
                raise RuntimeError("同机数据或 reader 所有权不一致")
            recorded_bytes = runtime.budget.used
            errors = scope.close()
            if (
                errors
                or runtime.budget.used != 0
                or arena.request_reclaim(receipt) != "released"
            ):
                raise RuntimeError("Scope/reader 清理或预算归还失败")
        report = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "policy": policy.model_dump(),
            "source_bytes": metadata.content_length,
            "source_sha256": metadata.checksum,
            "point_count": result.point_count,
            "dtype": "<f4",
            "array_bytes": array_bytes,
            "array_sha256": array_digest,
            "non_finite_positions": summary["invalid_counts"]["non_finite"],
            "filter_summary": summary,
            "local_array_sha256": local.source.content_sha256,
            "descriptor_sha256": local.source.descriptor_sha256,
            "arena_capacity_bytes": arena_capacity,
            "reader_reclaim_after_close": "released",
            "spatial_unit": result.spatial.length_unit,
            "read_verify_seconds": elapsed,
            "recorded_array_bytes": recorded_bytes,
            "budget_after_close": runtime.budget.used,
            "scope_closed": scope.closed,
            "assets": asset_results,
            "exchange": exchange_results,
            "nodes": node_results,
            "asset_policy": {
                "max_asset_bytes": args.asset_max_bytes,
                "max_archive_bytes": args.asset_archive_max_bytes,
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
    finally:
        scope.close()


if __name__ == "__main__":
    main()
