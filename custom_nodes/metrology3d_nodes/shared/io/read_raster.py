"""标定标量入口接入当前 CloudRuntime；原始输入与派生方法不混淆。"""

from backend.contracts.workflows.point_cloud_runtime import CloudRasterSource
from backend.service.application.workflows.point_cloud.raster_buffer import (
    borrow_raster_buffer,
)
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.io.file_snapshot import (
    checked_input_snapshot,
)
from custom_nodes.metrology3d_nodes.shared.io.raster_file import borrow_raster_file
from custom_nodes.metrology3d_nodes.shared.raster_conversion import convert_raster


def read_raster_file(
    *, runtime, object_store, project_id, file, file_format, spec, cancel
):
    """返回完整像素 owner 和冻结来源；供运行输入及原件资产恢复共用。"""
    with checked_input_snapshot(
        object_store=object_store,
        project_id=project_id,
        file=file,
        policy=runtime.policy,
        cancel=cancel,
    ) as (payload, stream):
        source = CloudRasterSource(
            kind="calibrated-raster",
            raster=spec,
            input_format=file_format,
            content_length=payload["content_length"],
            content_sha256=payload["checksum"],
            file_name=payload["file_name"],
            has_mask=False,
            file=payload,
        )
        with borrow_raster_file(
            stream,
            file_format,
            spec,
            policy=runtime.policy,
            budget=runtime.budget,
            cancel=cancel,
        ) as samples:
            try:
                result = convert_raster(
                    samples,
                    None,
                    spec,
                    policy=runtime.policy,
                    budget=runtime.budget,
                    scope=runtime.storage_scope,
                    cancel=cancel,
                )
            finally:
                samples = None
        return result, source


def _register(runtime, result, source, cancel):
    """发布引用及同次完整统计，不分配另一套索引或重扫数组。"""
    try:
        cloud = runtime.register_source(
            owner=result.arrays,
            point_count=source.raster.point_count(),
            fields=result.fields,
            spatial=source.raster.spatial,
            source=source,
            source_metadata=None,
            cancel=cancel,
        )
        return cloud, result.counts
    except BaseException as error:
        release_exception_frames(error)
        result.arrays.close()
        raise


def read_raster_reference(
    *, runtime, object_store, project_id, file, file_format, spec, cancel
):
    """返回引用和状态计数，全量解码与发布持有同一运行生命周期。"""
    with runtime.producing():
        result, source = read_raster_file(
            runtime=runtime,
            object_store=object_store,
            project_id=project_id,
            file=file,
            file_format=file_format,
            spec=spec,
            cancel=cancel,
        )
        return _register(runtime, result, source, cancel)


def read_raster_local(
    *, runtime, descriptor, expected_descriptor_sha256, acquire_view, cancel
):
    """返回引用和状态计数，输出拥有独立数组，不延长输入租约。"""
    with (
        runtime.producing(),
        borrow_raster_buffer(
            descriptor=descriptor,
            expected_descriptor_sha256=expected_descriptor_sha256,
            acquire_view=acquire_view,
            policy=runtime.policy,
            budget=runtime.budget,
            cancel=cancel,
        ) as borrowed,
    ):
        source = CloudRasterSource(
            kind="calibrated-raster",
            raster=descriptor.raster,
            input_format="array",
            content_length=descriptor.content_length,
            content_sha256=borrowed.content_sha256,
            has_mask=descriptor.has_mask,
            file_name=None,
            file=None,
        )
        result = convert_raster(
            borrowed.arrays["samples"],
            borrowed.arrays.get("mask"),
            descriptor.raster,
            policy=runtime.policy,
            budget=runtime.budget,
            scope=runtime.storage_scope,
            cancel=cancel,
        )
        return _register(runtime, result, source, cancel)
