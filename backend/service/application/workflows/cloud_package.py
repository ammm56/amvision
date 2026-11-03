"""三维配方携资源归档；复用资源 ZIP、保存校验和 App bundle 事务。"""

from dataclasses import replace
from hashlib import sha256
from tempfile import TemporaryFile
from zipfile import BadZipFile, ZipFile, ZIP_STORED

from backend.contracts.workflows.cloud_package import (
    WorkflowAppDocument,
    WorkflowCloudPackage,
    CloudPackageResource,
)
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.io.bounded_output import BoundedBinaryOutput
from backend.service.application.workflows.application_bundle_journal import (
    bundle_resource_identity,
)
from backend.service.application.workflows.documents.cloud_resource_archives import (
    validate_stored_members,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
    collect_measurement_references,
    reference_key,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


MAX_DOCUMENT_BYTES = 16 * 1024 * 1024


def retarget_cloud_document(document, *, project_id, application_id, template_id):
    """按目标新身份重建不可变契约，资源映射由后续事务执行。"""
    payload = document.model_dump(mode="json")
    payload["application"]["application_id"] = application_id
    payload["application"]["metadata"]["project_id"] = project_id
    payload["template"]["template_id"] = template_id
    payload["application"]["template_ref"].update(
        template_id=template_id,
        source_kind="embedded",
        source_uri=None,
    )
    return WorkflowAppDocument.model_validate(payload)


def check_package_document(document: WorkflowAppDocument) -> None:
    """三维资源包不假装携带模型部署或其他未实现的外部依赖。"""
    from backend.service.application.workflows.app_version_service import (
        _collect_stable_resource_references,
    )

    external = []
    _collect_stable_resource_references(
        document.model_dump(mode="json"), path="document", output=external
    )
    if external:
        raise InvalidRequestError(
            "三维配方包不包含模型、部署或外部规则资源", details={"references": external}
        )

    def reject_local_files(value):
        """临时 Run 引用和对象路径不是可搬运资源，不能悄悄漏包。"""
        if isinstance(value, dict):
            if any(
                value.get(key) for key in ("object_key", "mask_object_key", "lease_id")
            ):
                raise InvalidRequestError(
                    "配方包含运行引用或未打包的本地文件；应使用持久点云资源或调用时输入"
                )
            for item in value.values():
                reject_local_files(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                reject_local_files(item)

    reject_local_files(document.model_dump(mode="json"))
    if any(
        ref.kind != "point-cloud"
        for ref in collect_measurement_references(document.template)
    ):
        raise InvalidRequestError("三维配方包仅支持点云资源，不能遗漏二维计量资源")


def cloud_dependency_closure(resources, template, *, project_id, cancel):
    """按父项优先遍历不可变引用，拒绝缺失、跨项目、循环及同版本错摘要。"""
    ordered, state, identities = [], {}, {}

    def visit(ref):
        cancel()
        key = reference_key(ref)
        identity = (ref.project_id, ref.resource_id, ref.version)
        if identity in identities and identities[identity] != key:
            raise InvalidRequestError("同一资源版本出现不同内容摘要")
        identities[identity] = key
        if state.get(key) == "done":
            return
        if state.get(key) == "visiting":
            raise InvalidRequestError("点云依赖形成循环")
        if len(state) >= 64:
            raise InvalidRequestError("资源包最多包含 64 个版本（含父依赖）")
        if ref.kind != "point-cloud":
            raise InvalidRequestError("三维配方包仅支持点云资源")
        state[key] = "visiting"
        document = resources.read(ref, project_id=project_id)
        for parent in document.content.point_cloud.parent_assets:
            visit(parent)
        state[key] = "done"
        ordered.append(document)

    for reference in collect_measurement_references(template):
        visit(reference)
    return tuple(ordered)


def _copy(source, target, *, policy, cancel, limit):
    """块复制同时计算摘要；真实字节数始终受现有包预算限制。"""
    length, digest = 0, sha256()
    while True:
        cancel()
        block = source.read(policy.chunk_bytes)
        if not block:
            return length, digest.hexdigest()
        length += len(block)
        if length > limit:
            raise InvalidRequestError("配方包成员超过声明或显式限额")
        digest.update(block)
        if target.write(block) != len(block):
            raise OSError("配方包暂存短写")


def export_cloud_package(service, document, *, project_id, stream, policy, cancel):
    """导出编辑文档与完整父依赖；只读资源锁避免删除竞争，不触发执行。"""
    check_package_document(document)
    service.validate_application(
        project_id=project_id,
        application=document.application,
        template_override=document.template,
    )
    resources = MeasurementResourceService(service.dataset_storage, cloud_policy=policy)
    payload = document.model_dump(mode="json")
    payload["application"]["metadata"].pop("project_id", None)
    payload["application"]["template_ref"].update(
        source_kind="embedded", source_uri=None
    )
    document = WorkflowAppDocument.model_validate(payload)
    with resources.mutation(project_id):
        closure = cloud_dependency_closure(
            resources, document.template, project_id=project_id, cancel=cancel
        )
        output = BoundedBinaryOutput(stream, policy.max_archive_bytes, cancel)
        entries = []
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            for index, asset in enumerate(closure):
                with TemporaryFile(dir=service.dataset_storage.root_dir) as temporary:
                    resources.export_cloud_archive(
                        asset.reference,
                        project_id=project_id,
                        stream=temporary,
                        policy=policy,
                        cancel=cancel,
                    )
                    temporary.seek(0)
                    with archive.open(
                        f"resources/{index}.zip", "w", force_zip64=True
                    ) as target:
                        length, digest = _copy(
                            temporary,
                            target,
                            policy=policy,
                            cancel=cancel,
                            limit=policy.max_archive_bytes,
                        )
                entries.append(
                    CloudPackageResource(
                        reference=asset.reference,
                        name=asset.name,
                        byte_length=length,
                        sha256=digest,
                    )
                )
            manifest = WorkflowCloudPackage(
                format_id="amvision.workflow-cloud-package.v1",
                document=document,
                resources=tuple(entries),
            )
            metadata = manifest.model_dump_json().encode("utf-8")
            if len(metadata) > MAX_DOCUMENT_BYTES:
                raise InvalidRequestError("配方包描述超过 16 MiB")
            archive.writestr("package.json", metadata)
        output.flush()
        return output.count


class CloudPackageImport:
    """持有已打开归档；资源只暂存在现有 journal 中，提交后由 journal 清理。"""

    def __init__(self, archive, *, policy, cancel):
        """先核验成员、源身份和总体积；不接受任意解压路径或隐藏成员。"""
        self.archive, self.policy, self.cancel = archive, policy, cancel
        self.mapping = {}
        try:
            names = validate_stored_members(archive, max_entries=65)
            if (
                "package.json" not in names
                or archive.getinfo("package.json").file_size > MAX_DOCUMENT_BYTES
            ):
                raise ValueError("缺少配方描述或描述超过限额")
            self.manifest = WorkflowCloudPackage.model_validate_json(
                archive.read("package.json")
            )
            if set(names) != {
                "package.json",
                *(f"resources/{index}.zip" for index in range(self.count)),
            }:
                raise ValueError("配方包成员缺失或包含未知文件")
            if (
                sum(entry.file_size for entry in archive.infolist())
                > policy.max_archive_bytes
            ):
                raise ValueError("配方包成员总大小超过限额")
            identities = set()
            projects = set()
            for index, item in enumerate(self.manifest.resources):
                identity = (
                    item.reference.project_id,
                    item.reference.resource_id,
                    item.reference.version,
                )
                if (
                    identity in identities
                    or item.reference.kind != "point-cloud"
                    or (
                        archive.getinfo(f"resources/{index}.zip").file_size
                        != item.byte_length
                    )
                ):
                    raise ValueError("配方资源重复、类型或成员长度无效")
                identities.add(identity)
                projects.add(item.reference.project_id)
            if len(projects) > 1:
                raise ValueError("配方包资源跨源项目")
            check_package_document(self.manifest.document)
        except (BadZipFile, ValueError, KeyError, NotImplementedError) as error:
            raise InvalidRequestError(
                "三维配方包无效", details={"reason": str(error)}
            ) from error

    @property
    def count(self):
        """包含父依赖的资源数，用于事务预登记新资源所有权。"""
        return len(self.manifest.resources)

    def stage(self, journal, storage, *, project_id, template, actor_id):
        """逐个严格导入隔离存储；重算父引用摘要，不修改原始二进制。"""
        staged_storage = LocalDatasetStorage(
            replace(
                storage.settings,
                root_dir=str(storage.resolve(f"{journal.journal_root_key}/staging")),
            )
        )
        staged = MeasurementResourceService(staged_storage, cloud_policy=self.policy)
        for index, entry in enumerate(self.manifest.resources):
            self.cancel()
            with TemporaryFile(dir=staged_storage.root_dir) as temporary:
                with self.archive.open(f"resources/{index}.zip") as source:
                    length, digest = _copy(
                        source,
                        temporary,
                        policy=self.policy,
                        cancel=self.cancel,
                        limit=entry.byte_length,
                    )
                if (length, digest) != (entry.byte_length, entry.sha256):
                    raise InvalidRequestError("配方资源包摘要不匹配")
                temporary.seek(0)
                asset = staged.import_cloud_archive(
                    stream=temporary,
                    project_id=project_id,
                    name=entry.name,
                    write_identity=bundle_resource_identity(
                        journal.operation_id, index
                    ),
                    policy=self.policy,
                    cancel=self.cancel,
                    actor_id=actor_id,
                    expected_reference=entry.reference,
                    parent_references=self.mapping,
                )
            self.mapping[reference_key(entry.reference)] = asset.reference
        payload = template.model_dump(mode="json")
        for node in payload["nodes"]:
            if node["node_type_id"] in {
                "custom.metrology3d.read-cloud",
                "custom.metrology3d.export-cloud",
                "custom.metrology3d.save-cloud",
            }:
                field = (
                    "target"
                    if node["node_type_id"] == "custom.metrology3d.save-cloud"
                    else "source"
                )
                source = node["parameters"].get(field)
                if isinstance(source, dict) and source.get("kind") in {
                    "asset",
                    "new-version",
                }:
                    from backend.contracts.workflows.metrology import ResourceReference

                    key = reference_key(
                        ResourceReference.model_validate(source["reference"])
                    )
                    if key not in self.mapping:
                        raise InvalidRequestError("配方缺少直接引用的点云资源")
                    source["reference"] = self.mapping[key].model_dump(mode="json")
        result = WorkflowGraphTemplate.model_validate(payload)
        actual = cloud_dependency_closure(
            staged, result, project_id=project_id, cancel=self.cancel
        )
        if {reference_key(asset.reference) for asset in actual} != {
            reference_key(ref) for ref in self.mapping.values()
        }:
            raise InvalidRequestError("配方包包含未被引用的额外资源")
        return result

    def install(self, journal, storage):
        """调用方持有目标项目资源锁，原子移动已校验目录且禁止覆盖。"""
        for key in journal.created_resource_keys:
            self.cancel()
            storage.move_tree(f"{journal.journal_root_key}/staging/{key}", key)
