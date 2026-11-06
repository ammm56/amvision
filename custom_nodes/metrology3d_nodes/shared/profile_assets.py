"""轮廓原件沿现有点云资产保存；行表与点数据同属一个资源版本。"""

from backend.contracts.workflows.measurement_resources import MeasurementResourceContent
from backend.contracts.workflows.point_cloud_assets import (
    AssetProvenance,
    CloudBlob,
    ProfileCloudAsset,
)
from backend.contracts.workflows.profile3d import ProfileSource
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    cloud_blob_key,
)
from custom_nodes.metrology3d_nodes.shared.io.read_profiles import read_profile_file


def freeze_profile_source(source):
    """仅剥离运行访问引用，保留标定、字节和完整原行表身份。"""
    return ProfileSource.model_validate(source.model_dump(exclude={"file"}))


def original_profile_content(reference):
    """原文件不重编码，正文声明全部原值字段和转换标定。"""
    source = freeze_profile_source(reference.source)
    cloud = ProfileCloudAsset(
        format_id="amvision.point-cloud-asset.v1",
        kind="point-cloud",
        representation="profiles-original",
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


def restore_profile_asset(runtime, document, service, project_id, cancel):
    """使用同一严格 NPZ 解码器，恢复新运行的点和行表所有者。"""
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
    result, rows, source = read_profile_file(
        runtime=runtime,
        object_store=service.storage,
        project_id=project_id,
        file=file,
        spec=cloud.source.profiles,
        has_validity=cloud.source.has_validity,
        cancel=cancel,
    )
    try:
        if (
            result.fields != cloud.fields
            or freeze_profile_source(source) != cloud.source
        ):
            raise InvalidRequestError("轮廓原件解码与已保存标定或行表不一致")
        return runtime.register_asset(
            owner=result.arrays,
            document=document,
            indices=None,
            cancel=cancel,
            profile_rows=rows,
        )
    except BaseException as error:
        release_exception_frames(error)
        result.arrays.close()
        rows.close()
        raise
