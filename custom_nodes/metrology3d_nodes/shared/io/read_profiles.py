"""文件/同机轮廓输入接入已有 CloudRuntime，原行表不依赖调用方租约。"""

from backend.contracts.workflows.point_cloud_runtime import CloudProfileSource
from backend.contracts.workflows.point_cloud import FIELD_WIDTHS
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.profile_buffer import (
    borrow_profile_buffer,
)
from backend.service.application.workflows.point_cloud.profile_rows import (
    retain_profile_rows,
    row_digest,
)
from custom_nodes.metrology3d_nodes.shared.io.file_snapshot import (
    checked_input_snapshot,
)
from custom_nodes.metrology3d_nodes.shared.io.profile_file import borrow_profile_file
from custom_nodes.metrology3d_nodes.shared.profile_conversion import convert_profiles


def _convert(runtime, arrays, spec, has_validity, cancel):
    """一次输入借用内完成行表留存与点投影，任何失败一起释放。"""
    retained = spec.row_bytes() + spec.point_count * sum(
        FIELD_WIDTHS[f.dtype] * f.components
        for f in spec.cloud_fields(has_validity=has_validity)
    )
    if retained > runtime.policy.max_decoded_bytes:
        raise InvalidRequestError("轮廓输出及原行表超过联合解码预算")
    rows, result = None, None
    try:
        rows = retain_profile_rows(arrays, spec, runtime=runtime, cancel=cancel)
        result = convert_profiles(
            arrays,
            spec,
            has_validity=has_validity,
            policy=runtime.policy,
            budget=runtime.budget,
            scope=runtime.storage_scope,
            cancel=cancel,
        )
        digest = row_digest(arrays, spec, policy=runtime.policy, cancel=cancel)
        return result, rows, digest
    except BaseException as error:
        release_exception_frames(error)
        if result is not None:
            result.arrays.close()
        if rows is not None:
            rows.close()
        raise


def read_profile_file(
    *, runtime, object_store, project_id, file, spec, has_validity, cancel
):
    """复用不可变文件快照；返回由本次 Scope 持有的点数组及完整行表。"""
    result, rows = None, None
    try:
        with checked_input_snapshot(
            object_store=object_store,
            project_id=project_id,
            file=file,
            policy=runtime.policy,
            cancel=cancel,
        ) as (payload, stream):
            with borrow_profile_file(
                stream,
                spec,
                has_validity=has_validity,
                policy=runtime.policy,
                budget=runtime.budget,
                cancel=cancel,
            ) as arrays:
                try:
                    result, rows, digest = _convert(
                        runtime, arrays, spec, has_validity, cancel
                    )
                finally:
                    arrays = None
            source = CloudProfileSource(
                kind="calibrated-profiles",
                profiles=spec,
                input_format="npz",
                content_length=payload["content_length"],
                content_sha256=payload["checksum"],
                file_name=payload["file_name"],
                file=payload,
                has_validity=has_validity,
                row_table_sha256=digest,
            )
        return result, rows, source
    except BaseException as error:
        release_exception_frames(error)
        if result is not None:
            result.arrays.close()
        if rows is not None:
            rows.close()
        raise


def _register(runtime, result, rows, source, cancel):
    """点与行表共同准入，失败不得留下未发布数组。"""
    try:
        cloud = runtime.register_source(
            owner=result.arrays,
            point_count=source.profiles.point_count,
            fields=result.fields,
            spatial=source.profiles.spatial,
            source=source,
            source_metadata=None,
            profile_rows=rows,
            cancel=cancel,
        )
        return cloud, result.counts
    except BaseException as error:
        release_exception_frames(error)
        result.arrays.close()
        rows.close()
        raise


def read_profile_reference(
    *, runtime, object_store, project_id, file, spec, has_validity, cancel
):
    """严格文件入口完成后才发布新的运行引用。"""
    with runtime.producing():
        result, rows, source = read_profile_file(
            runtime=runtime,
            object_store=object_store,
            project_id=project_id,
            file=file,
            spec=spec,
            has_validity=has_validity,
            cancel=cancel,
        )
        return _register(runtime, result, rows, source, cancel)


def read_profile_local(
    *, runtime, descriptor, expected_descriptor_sha256, acquire_view, cancel
):
    """接同机只读 guard；复制完成后不延长外部输入租约。"""
    with runtime.producing():
        result, rows = None, None
        try:
            with borrow_profile_buffer(
                descriptor=descriptor,
                expected_descriptor_sha256=expected_descriptor_sha256,
                acquire_view=acquire_view,
                policy=runtime.policy,
                budget=runtime.budget,
                cancel=cancel,
            ) as borrowed:
                result, rows, digest = _convert(
                    runtime,
                    borrowed.arrays,
                    descriptor.profiles,
                    descriptor.has_validity,
                    cancel,
                )
                source = CloudProfileSource(
                    kind="calibrated-profiles",
                    profiles=descriptor.profiles,
                    input_format="array",
                    content_length=descriptor.content_length,
                    content_sha256=borrowed.content_sha256,
                    file_name=None,
                    file=None,
                    has_validity=descriptor.has_validity,
                    row_table_sha256=digest,
                )
            # 外部 guard 正常退出后才公开引用，退出错误不能留下已发布记录。
            return _register(runtime, result, rows, source, cancel)
        except BaseException as error:
            release_exception_frames(error)
            if result is not None:
                result.arrays.close()
            if rows is not None:
                rows.close()
            raise
