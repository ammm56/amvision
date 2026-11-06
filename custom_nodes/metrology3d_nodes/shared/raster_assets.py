"""标量原件资产沿既有资源服务保存和恢复，不新增资源类型或存储系统。"""

from backend.contracts.workflows.measurement_resources import MeasurementResourceContent
from backend.contracts.workflows.point_cloud_assets import (
    AssetProvenance,
    CloudBlob,
    RasterCloudAsset,
)
from backend.contracts.workflows.raster3d import RasterSource
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    cloud_blob_key,
)
from custom_nodes.metrology3d_nodes.shared.io.read_raster import read_raster_file


def freeze_raster_source(source):
    """持久正文只移除运行文件引用，标定和原字节摘要完整保留。"""
    return RasterSource.model_validate(source.model_dump(exclude={"file"}))


def original_raster_content(reference):
    """原文件逐字节保存，解码参数与所有字段参与资产摘要。"""
    source = freeze_raster_source(reference.source)
    cloud = RasterCloudAsset(
        format_id="amvision.point-cloud-asset.v1",
        kind="point-cloud",
        representation="raster-original",
        source=source,
        spatial=reference.spatial,
        provenance=AssetProvenance(method=None, parents=(), source_retained=True),
        blobs=(
            CloudBlob(
                role="original",
                name="original.bin",
                content_length=source.content_length,
                sha256=source.content_sha256,
            ),
        ),
        source_field_names=(),
        parent_assets=(),
        point_count=reference.point_count,
        source_metadata=None,
        fields=reference.fields,
        vertex_kind="source",
        topology=None,
    )
    return MeasurementResourceContent(kind="point-cloud", point_cloud=cloud)


def restore_raster_asset(runtime, document, service, project_id, cancel):
    """先经同一快照/标定解码器核验，成功后发布新的 run 身份。"""
    cloud = document.content.point_cloud
    blob = cloud.blobs[0]
    file = dict(
        transport_kind="storage",
        storage_ref="object-store",
        object_key=cloud_blob_key(service, document.reference, blob),
        file_name=cloud.source.file_name,
        media_type="application/octet-stream",
        content_length=blob.content_length,
        checksum_algorithm="sha256",
        checksum=blob.sha256,
        immutable_version=f"sha256:{blob.sha256}",
    )
    result, source = read_raster_file(
        runtime=runtime,
        object_store=service.storage,
        project_id=project_id,
        file=file,
        file_format=cloud.source.input_format,
        spec=cloud.source.raster,
        cancel=cancel,
    )
    try:
        if (
            result.fields != cloud.fields
            or freeze_raster_source(source) != cloud.source
        ):
            raise InvalidRequestError("标量原件解码与资产声明不一致")
        return runtime.register_asset(
            owner=result.arrays, document=document, indices=None, cancel=cancel
        )
    except BaseException as error:
        release_exception_frames(error)
        result.arrays.close()
        raise
