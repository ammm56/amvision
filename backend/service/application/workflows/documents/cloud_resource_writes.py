"""现有计量资源版本中的点云提交；沿用项目写锁和 version.json。"""

from datetime import datetime, timezone
from hashlib import sha256
from pydantic import TypeAdapter

from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceContentV2,
    MeasurementResourceDocument,
)
from backend.contracts.workflows.metrology import ResourceReference
from backend.contracts.workflows.point_cloud import Sha256
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceConflictError,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    CloudAssetPolicy,
    cloud_blob_key,
    verify_cloud_blobs,
)


def save_cloud_resource(
    service,
    *,
    project_id: str,
    name: str,
    content: MeasurementResourceContentV2,
    streams,
    write_identity: str,
    policy: CloudAssetPolicy,
    cancel,
    expected_base: ResourceReference | None = None,
    actor_id: str | None = None,
):
    """同次执行幂等，数据核验后一次提交；提交成功后不再响应取消。"""
    from backend.service.application.workflows.documents.measurement_resources import (
        canonical_bytes,
        _MAX_DOCUMENT_BYTES,
    )

    content = MeasurementResourceContentV2.model_validate(content)
    identity = TypeAdapter(Sha256).validate_python(write_identity)
    if (
        content.kind != "point-cloud"
        or not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 128
    ):
        raise InvalidRequestError("点云保存类型或名称无效")
    cloud = content.point_cloud
    payload = canonical_bytes(content)
    if (
        len(payload) > _MAX_DOCUMENT_BYTES
        or sum(b.content_length for b in cloud.blobs) > policy.max_asset_bytes
    ):
        raise InvalidRequestError("点云资产描述或数据超过显式预算")
    if set(streams) != {b.name for b in cloud.blobs}:
        raise InvalidRequestError("点云资产流与数据块不一致")
    if expected_base is not None:
        expected_base = ResourceReference.model_validate(expected_base)
        if (
            expected_base.project_id != project_id
            or expected_base.kind != "point-cloud"
        ):
            raise InvalidRequestError("点云基版本不属于当前项目或类型")
    resource_id = (
        expected_base.resource_id if expected_base else f"measurement-cloud-{identity}"
    )
    reference = ResourceReference(
        project_id=project_id,
        resource_id=resource_id,
        version=expected_base.version + 1 if expected_base else 1,
        sha256=sha256(payload).hexdigest(),
        kind="point-cloud",
    )
    key = service.version_key(reference)
    version_root = key.rsplit("/", 1)[0]
    with service.mutation(project_id):
        cancel()
        if service.storage.resolve(key).exists():
            existing = service.get_version(
                project_id=project_id,
                resource_id=resource_id,
                version=reference.version,
            )
            if (
                existing.write_identity != identity
                or existing.reference != reference
                or existing.name != name.strip()
            ):
                raise ResourceConflictError("点云保存身份冲突或基版本已更新")
            # 重入仍校验此次载荷；不能因 manifest 相同而把损坏的重传报告成功。
            for blob in cloud.blobs:
                submitted = CheckedBlobStream(streams[blob.name], blob, cancel, cloud)
                while submitted.read(policy.chunk_bytes):
                    pass
            verify_cloud_blobs(service, existing, policy=policy, cancel=cancel)
            return existing
        if service.storage.resolve(f"{version_root}/deleted.json").exists():
            raise ResourceConflictError("已删除的点云版本不能被重复提交恢复")
        if expected_base is not None:
            service.read(expected_base, project_id=project_id)
            versions = service.storage.resolve(key).parent.parent
            if any(
                p.is_dir() and p.name.isdecimal() and int(p.name) > reference.version
                for p in versions.iterdir()
            ):
                raise ResourceConflictError("点云基版本不是当前版本")
        for parent in cloud.parent_assets:
            if parent.project_id != project_id or (
                parent.resource_id == resource_id
                and parent.version >= reference.version
            ):
                raise InvalidRequestError("点云父资源跨项目或形成自引用")
            # 已提交父只能指向更早的不可变内容，不能回指尚未提交的本版本。
            parent_doc = service.read(parent, project_id=project_id)
            if (
                cloud.provenance.source_retained
                and not parent_doc.content.point_cloud.provenance.source_retained
            ):
                raise InvalidRequestError("点云父资产没有保留完整原始来源")
            verify_cloud_blobs(service, parent_doc, policy=policy, cancel=cancel)
        document = MeasurementResourceDocument(
            reference=reference,
            name=name.strip(),
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
            created_by=actor_id,
            write_identity=identity,
        )
        if len(document.model_dump_json().encode("utf-8")) > _MAX_DOCUMENT_BYTES:
            raise InvalidRequestError("点云版本记录超过描述预算")
        # 此目录没有提交标记，先清理上次中断留下的固定对象，绝不覆盖已提交版本。
        service.storage.delete_tree(version_root + "/immutable")
        try:
            for blob in cloud.blobs:
                checked = CheckedBlobStream(streams[blob.name], blob, cancel, cloud)
                receipt = service.storage.write_immutable_stream(
                    object_prefix=version_root,
                    source_stream=checked,
                    media_type="application/octet-stream",
                    extension=".bin",
                    chunk_size=policy.chunk_bytes,
                    max_bytes=max(1, blob.content_length),
                )
                if (
                    not checked.complete
                    or receipt.metadata.object_key
                    != cloud_blob_key(service, reference, blob)
                    or receipt.metadata.content_length != blob.content_length
                    or receipt.metadata.checksum != blob.sha256
                ):
                    raise InvalidRequestError("点云数据块提交身份不一致")
            cancel()
            service.storage.write_json(key, document.model_dump(mode="json"))
        except BaseException:
            # write_json 可能已 replace 后才报错；已提交版本的副作用不能被回滚成坏引用。
            if not service.storage.resolve(key).exists():
                service.storage.delete_tree(version_root + "/immutable")
            raise
        return document
