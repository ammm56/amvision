"""B06 标定栅格节点；两种入口共用全精度投影与当前运行资源。"""

from backend.contracts.workflows.raster3d import RasterToCloudParameters
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.point_cloud.trigger_input import (
    require_raster_handoff,
)
from custom_nodes.metrology3d_nodes.shared.io.read_raster import (
    read_raster_local,
    read_raster_reference,
)
from custom_nodes.metrology3d_nodes.shared.node_runtime import require_node_runtime
from backend.nodes.core_nodes.support.logic import build_value_payload


def raster_to_cloud(request):
    """文件标定来自参数，数组标定来自可信载荷；不允许两者混用。"""
    settings = RasterToCloudParameters.model_validate(request.parameters).settings
    env = require_node_runtime(request)
    env.cancel()
    file = request.input_values.get("file")
    raster = request.input_values.get("raster")
    if settings.kind == "file":
        if file is None or raster is not None:
            raise InvalidRequestError("文件模式需要 file，且不能同时传入 raster")
        cloud, counts = read_raster_reference(
            runtime=env.runtime,
            object_store=env.service.storage,
            project_id=env.project_id,
            file=file,
            file_format=settings.file_format,
            spec=settings.raster,
            cancel=env.cancel,
        )
    else:
        if raster is None or file is not None:
            raise InvalidRequestError("同机数组模式需要 raster，且不能同时传入 file")
        payload = require_raster_handoff(request.execution_metadata, raster)
        reader = request.runtime_context.local_buffer_reader
        if reader is None:
            raise ServiceConfigurationError("同机标量输入缺少 LocalBuffer reader")
        cloud, counts = read_raster_local(
            runtime=env.runtime,
            descriptor=payload.descriptor,
            expected_descriptor_sha256=payload.descriptor_sha256,
            acquire_view=lambda: reader.acquire_buffer_ref_view(payload.buffer_ref),
            cancel=env.cancel,
        )
    return {
        "cloud": cloud.model_dump(mode="json"),
        "summary": build_value_payload(_summary(cloud, counts)),
    }


def _summary(cloud, counts):
    """复用本次成功转换的完整统计，不借用或再扫描点云数组。"""
    spec = cloud.source.raster
    return dict(
        width=spec.width,
        height=spec.height,
        source_point_count=cloud.point_count,
        calibration_id=spec.calibration_id,
        calibration_revision=spec.calibration_revision,
        status_counts=dict(counts),
    )
