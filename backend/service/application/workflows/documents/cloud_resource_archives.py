"""点云资产的有界 ZIP_STORED 交换；不持有完整归档 bytes。"""

from contextlib import ExitStack
from zipfile import BadZipFile, ZipFile, ZIP_STORED

from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceContent,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.io.bounded_output import BoundedBinaryOutput
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    cloud_blob_key,
)


def export_cloud_archive(service, reference, *, project_id, stream, policy, cancel):
    """输出当前资产字节及父引用，不隐式复制父资产；失败时丢弃未交付输出。"""
    from backend.service.application.workflows.documents.measurement_resources import (
        canonical_bytes,
    )

    document = service.read(reference, project_id=project_id)
    if reference.kind != "point-cloud":
        raise InvalidRequestError("流式点云归档入口仅接收 point-cloud")
    cloud = document.content.point_cloud
    if sum(b.content_length for b in cloud.blobs) > policy.max_asset_bytes:
        raise InvalidRequestError("点云资产超过显式容量")
    target = BoundedBinaryOutput(stream, policy.max_archive_bytes, cancel)
    with ZipFile(target, "w", compression=ZIP_STORED) as archive:
        archive.writestr("resource.json", canonical_bytes(document.content))
        for blob in cloud.blobs:
            with (
                service.storage.open_read_snapshot(
                    cloud_blob_key(service, reference, blob)
                ) as snapshot,
                archive.open(blob.name, "w", force_zip64=True) as output,
            ):
                checked = CheckedBlobStream(snapshot.stream, blob, cancel, cloud)
                while chunk := checked.read(policy.chunk_bytes):
                    if output.write(chunk) != len(chunk):
                        raise OSError("点云归档成员短写")
    target.flush()
    return target.count


def import_cloud_archive(
    service, *, stream, project_id, name, write_identity, policy, cancel, actor_id=None
):
    """精确成员 allowlist、真实长度/CRC/摘要验证后提交新资源。"""
    from backend.service.application.workflows.documents.measurement_resources import (
        _MAX_DOCUMENT_BYTES,
    )

    stream.seek(0, 2)
    length = stream.tell()
    if length <= 0 or length > policy.max_archive_bytes:
        raise InvalidRequestError("点云资产包大小无效或超过显式限额")
    stream.seek(0)
    try:
        with ZipFile(stream) as archive, ExitStack() as stack:
            entries = archive.infolist()
            names = [e.filename for e in entries]
            if (
                len(names) != len(set(names))
                or not 2 <= len(names) <= 3
                or "resource.json" not in names
            ):
                raise ValueError("点云资产包成员无效")
            for entry in entries:
                mode = (entry.external_attr >> 16) & 0o170000
                if (
                    entry.compress_type != ZIP_STORED
                    or entry.flag_bits & 1
                    or mode not in (0, 0o100000)
                    or entry.is_dir()
                ):
                    raise ValueError("点云资产包不能包含压缩、加密、链接或目录")
            if archive.getinfo("resource.json").file_size > _MAX_DOCUMENT_BYTES:
                raise ValueError("点云资产描述超过限额")
            content = MeasurementResourceContent.model_validate_json(
                archive.read("resource.json")
            )
            if content.kind != "point-cloud":
                raise ValueError("资产包不是 point-cloud")
            cloud = content.point_cloud
            if set(names) != {"resource.json", *(b.name for b in cloud.blobs)}:
                raise ValueError("点云资产包包含遗漏或未知成员")
            if sum(b.content_length for b in cloud.blobs) > policy.max_asset_bytes:
                raise ValueError("点云资产数据超过限额")
            streams = {}
            for blob in cloud.blobs:
                if archive.getinfo(blob.name).file_size != blob.content_length:
                    raise ValueError("点云资产成员长度不匹配")
                streams[blob.name] = stack.enter_context(archive.open(blob.name))
            return service.save_cloud(
                project_id=project_id,
                name=name,
                content=content,
                streams=streams,
                write_identity=write_identity,
                policy=policy,
                cancel=cancel,
                actor_id=actor_id,
            )
    except (BadZipFile, ValueError, NotImplementedError) as exc:
        raise InvalidRequestError("点云资产包无效") from exc
