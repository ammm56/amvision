"""Workflow 计量资源：不可变保存、完整性验证、引用保护与有限准备缓存。"""

from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import re
from itertools import islice
from threading import Lock
from types import MappingProxyType
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZIP_STORED

from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceContent,
    MeasurementResourceDocument,
)
from backend.contracts.workflows.metrology import ResourceReference
from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
    ResourceConflictError,
    ResourceInUseError,
    ResourceNotFoundError,
)
from backend.service.application.runtime.io.path_write_coordinator import (
    PathWriteCoordinator,
)
from backend.service.application.workflows.documents.storage import normalize_identifier

_coordinator = PathWriteCoordinator()
_MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
_MAX_IMAGE_BYTES = 64 * 1024 * 1024
_RESOURCE_FIELDS = {
    "calibration_resource": "planar-calibration",
    "template_resource": "localization-template",
}


def _path_identifier(value: str, field: str) -> str:
    """Windows/Linux 一致的路径身份，禁止 ADS、尾点和保留设备名。"""
    value = normalize_identifier(value, field)
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
        or value.endswith(".")
        or re.fullmatch(
            r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value, re.IGNORECASE
        )
    ):
        raise InvalidRequestError(f"{field} 不是有效的资源路径 ID")
    return value


def canonical_bytes(content: MeasurementResourceContent) -> bytes:
    """稳定编码，确保导入、发布与运行时校验采用同一内容摘要。"""
    return json.dumps(
        content.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def collect_measurement_references(template) -> tuple[ResourceReference, ...]:
    """只读取显式资源参数；旧图无引用时不访问存储。"""
    references = {}
    for node in template.nodes:
        for field, kind in _RESOURCE_FIELDS.items():
            value = node.parameters.get(field)
            if value is None:
                continue
            # 其他包可以使用相同参数名；没有计量资源声明时不把它升级为平台资源。
            if node.node_type_id not in {
                "custom.opencv.rigid-locate",
                "custom.connector.measure",
            } and (
                not isinstance(value, dict)
                or value.get("kind") not in _RESOURCE_FIELDS.values()
            ):
                continue
            try:
                reference = ResourceReference.model_validate(value)
                if reference.kind != kind:
                    raise ValueError("计量资源参数类型不匹配")
            except ValueError as exc:
                raise InvalidRequestError(
                    str(exc), details={"node_id": node.node_id, "field": field}
                ) from exc
            references[reference.model_dump_json()] = reference
    if len(references) > 64:
        raise InvalidRequestError("单个 Workflow 最多引用 64 个计量资源版本")
    return tuple(references.values())


def reference_key(reference: ResourceReference) -> str:
    """缓存采用完整引用，禁止只按名称或最新版本复用。"""
    return reference.model_dump_json()


class MeasurementResourceService:
    """资源属于 Project；保存发布删除使用同一个跨进程非等待路径锁。"""

    def __init__(self, storage):
        """保存 ObjectStore；管理接口不触发工作流执行。"""
        self.storage = storage

    def root(self, project_id: str) -> str:
        """资源路径只由校验后的项目 ID 生成。"""
        project_id = _path_identifier(project_id, "project_id")
        return f"workflows/projects/{project_id}/measurement-resources"

    def version_key(self, reference: ResourceReference) -> str:
        """拒绝路径注入；客户端不能指定磁盘路径。"""
        resource_id = _path_identifier(reference.resource_id, "resource_id")
        return f"{self.root(reference.project_id)}/{resource_id}/versions/{reference.version}/version.json"

    @contextmanager
    def mutation(self, project_id: str):
        """仅管理面互斥，冲突明确返回；不等待、不影响推理数据面。"""
        with _coordinator.try_acquire(
            [self.storage.resolve(self.root(project_id))]
        ) as acquired:
            if not acquired:
                raise ResourceConflictError(
                    "当前 Project 的计量资源正在修改，请完成当前操作后再提交"
                )
            try:
                yield
            except OSError as exc:
                raise PersistenceOperationError(
                    "计量资源文件操作失败，请检查文件占用、权限或磁盘空间后重新操作",
                    details={
                        "project_id": project_id,
                        "errno": exc.errno,
                        "winerror": getattr(exc, "winerror", None),
                    },
                ) from exc

    def save(
        self,
        *,
        project_id: str,
        name: str,
        content: MeasurementResourceContent,
        image_bytes: bytes | None = None,
        resource_id: str | None = None,
        actor_id: str | None = None,
    ) -> MeasurementResourceDocument:
        """每次保存新版本，历史版本不可覆盖；最后原子提交版本 JSON。"""
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128:
            raise InvalidRequestError("计量资源名称必须为 1–128 个非空字符")
        self._validate_image(content, image_bytes)
        resource_id = _path_identifier(
            resource_id or f"measurement-{uuid4().hex}", "resource_id"
        )
        with self.mutation(project_id):
            versions = self.storage.resolve(
                f"{self.root(project_id)}/{resource_id}/versions"
            )
            # 目录序号不删除，用作 tombstone，防止删除后重用旧版本。
            sequence = (
                [
                    int(p.name)
                    for p in versions.iterdir()
                    if p.is_dir() and p.name.isdecimal()
                ]
                if versions.exists()
                else []
            )
            reference = ResourceReference(
                project_id=project_id,
                resource_id=resource_id,
                version=max(sequence, default=0) + 1,
                sha256=hashlib.sha256(canonical_bytes(content)).hexdigest(),
                kind=content.kind,
            )
            key = self.version_key(reference)
            image_key = (
                f"{key.rsplit('/', 1)[0]}/immutable/sha256-{content.template.image_sha256}/content.png"
                if content.template
                else None
            )
            document = MeasurementResourceDocument(
                reference=reference,
                name=name.strip(),
                content=content,
                image_object_key=image_key,
                created_at=datetime.now(timezone.utc).isoformat(),
                created_by=actor_id,
            )
            if image_bytes is not None:
                receipt = self.storage.write_immutable_object(
                    object_prefix=key.rsplit("/", 1)[0],
                    content=image_bytes,
                    media_type="image/png",
                    extension=".png",
                )
                if receipt.metadata.object_key != image_key:
                    raise InvalidRequestError("计量参考图存储身份不一致")
            self.storage.write_json(key, document.model_dump(mode="json"))
            return self.read(reference, project_id=project_id)

    def read(
        self, reference: ResourceReference, *, project_id: str
    ) -> MeasurementResourceDocument:
        """校验归属、完整引用、内容 hash 和固定的图片对象路径。"""
        if reference.project_id != project_id:
            raise InvalidRequestError("计量资源不属于当前 Project")
        key = self.version_key(reference)
        path = self.storage.resolve(key)
        if not path.is_file():
            raise ResourceNotFoundError(
                "计量资源版本不存在",
                details={
                    "resource_id": reference.resource_id,
                    "version": reference.version,
                },
            )
        if path.stat().st_size > _MAX_DOCUMENT_BYTES:
            raise InvalidRequestError("计量资源描述超过 4 MB")
        try:
            document = MeasurementResourceDocument.model_validate_json(
                path.read_bytes()
            )
            if (
                document.reference != reference
                or hashlib.sha256(canonical_bytes(document.content)).hexdigest()
                != reference.sha256
                or document.content.kind != reference.kind
            ):
                raise ValueError("计量资源身份或内容摘要不匹配")
            expected = None
            if document.content.template is not None:
                expected = f"{key.rsplit('/', 1)[0]}/immutable/sha256-{document.content.template.image_sha256}/content.png"
            if document.image_object_key != expected:
                raise ValueError("计量资源图片路径不匹配")
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc
        return document

    def image_bytes(self, document: MeasurementResourceDocument) -> bytes | None:
        """准备期读取参考图；运行中的节点借用只读矩阵。"""
        if document.image_object_key is None:
            return None
        path = self.storage.resolve(document.image_object_key)
        if not path.is_file() or path.stat().st_size > _MAX_IMAGE_BYTES:
            raise InvalidRequestError("计量参考图不存在或超过 64 MB")
        image = path.read_bytes()
        self._validate_image(document.content, image, decode=False)
        return image

    @staticmethod
    def _validate_image(content, image_bytes, *, decode=True):
        """先检查 PNG 头与预算再解码，不用生成图替代真实精度验收。"""
        if content.template is None:
            if image_bytes is not None:
                raise InvalidRequestError("平面标定资源不能携带参考图片")
            return
        if (
            image_bytes is None
            or len(image_bytes) > _MAX_IMAGE_BYTES
            or image_bytes[:8] != b"\x89PNG\r\n\x1a\n"
            or len(image_bytes) < 33
        ):
            raise InvalidRequestError("定位模板需要不超过 64 MB 的 PNG 参考原图")
        template = content.template
        width, height = (
            int.from_bytes(image_bytes[16:20], "big"),
            int.from_bytes(image_bytes[20:24], "big"),
        )
        if (width, height) != (
            template.image_width,
            template.image_height,
        ) or hashlib.sha256(image_bytes).hexdigest() != template.image_sha256:
            raise InvalidRequestError("参考图片尺寸或内容摘要不匹配")
        if not decode:
            return
        import cv2
        import numpy as np

        image = cv2.imdecode(
            np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED
        )
        if image is None or image.shape[:2] != (height, width):
            raise InvalidRequestError("参考图片无法完整解码")

    def validate_template(self, template, *, project_id: str):
        """发布前验证全部实际资源，不能只冻结资源名称。"""
        refs = collect_measurement_references(template)
        for ref in refs:
            document = self.read(ref, project_id=project_id)
            self._validate_image(document.content, self.image_bytes(document))
        return refs

    def list_versions(self, *, project_id: str):
        """列表仅显示已提交的版本，损坏文件明确报错。"""
        root = self.storage.resolve(self.root(project_id))
        paths = sorted(islice(root.glob("*/versions/*/version.json"), 4097))
        if len(paths) > 4096:
            raise InvalidRequestError("计量资源版本数超过管理列表限制 4096")
        if any(not p.parent.name.isdecimal() for p in paths):
            raise InvalidRequestError("计量资源版本目录损坏")
        return [
            self.get_version(
                project_id=project_id,
                resource_id=p.parent.parent.parent.name,
                version=int(p.parent.name),
            )
            for p in paths
        ]

    def get_version(
        self,
        *,
        project_id: str,
        resource_id: str,
        version: int,
        include_deleted: bool = False,
    ):
        """管理接口按明确版本读取，随后按记录中的完整引用复核。"""
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or not 1 <= version <= 2147483647
        ):
            raise InvalidRequestError("计量资源版本号无效")
        resource_id = _path_identifier(resource_id, "resource_id")
        path = self.storage.resolve(
            f"{self.root(project_id)}/{resource_id}/versions/{version}/version.json"
        )
        deleted = include_deleted and not path.exists()
        if deleted:
            path = path.with_name("deleted.json")
        if not path.is_file():
            raise ResourceNotFoundError("计量资源版本不存在")
        if path.stat().st_size > _MAX_DOCUMENT_BYTES:
            raise InvalidRequestError("计量资源描述超过 4 MB")
        try:
            document = MeasurementResourceDocument.model_validate_json(
                path.read_bytes()
            )
        except ValueError as exc:
            raise InvalidRequestError("计量资源版本记录损坏") from exc
        if (
            document.reference.project_id,
            document.reference.resource_id,
            document.reference.version,
        ) != (project_id, resource_id, version):
            raise InvalidRequestError("计量资源路径与记录身份不一致")
        if deleted:
            return document
        return self.read(document.reference, project_id=project_id)

    def delete(self, reference: ResourceReference, *, project_id: str):
        """引用存在时禁止删除；保存删除凭据，文件占用导致失败后可再次清理。"""
        with self.mutation(project_id):
            version_path = self.storage.resolve(self.version_key(reference))
            tombstone = version_path.with_name("deleted.json")
            if not version_path.exists() and tombstone.is_file():
                if (
                    reference.project_id != project_id
                    or tombstone.stat().st_size > _MAX_DOCUMENT_BYTES
                ):
                    raise InvalidRequestError("计量资源删除凭据无效")
                try:
                    document = MeasurementResourceDocument.model_validate_json(
                        tombstone.read_bytes()
                    )
                    if (
                        document.reference != reference
                        or hashlib.sha256(canonical_bytes(document.content)).hexdigest()
                        != reference.sha256
                    ):
                        raise ValueError("计量资源删除凭据不匹配")
                except ValueError as exc:
                    raise InvalidRequestError(str(exc)) from exc
                # 已完成引用校验并撤销可见性；重试只清理固定版本下的 immutable 目录。
                self.storage.delete_tree(
                    self.version_key(reference).rsplit("/", 1)[0] + "/immutable"
                )
                return
            document = self.read(reference, project_id=project_id)
            project = self.storage.resolve(
                f"workflows/projects/{normalize_identifier(project_id, 'project_id')}"
            )
            # 草稿与发布快照都包含 template.json；损坏或超限时不能推定无引用。
            templates = list(islice(project.rglob("template.json"), 10001))
            if len(templates) > 10000:
                raise ResourceConflictError(
                    "Workflow 文档过多，不能安全确认计量资源引用"
                )
            from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate

            for path in templates:
                if path.stat().st_size > 32 * 1024 * 1024:
                    raise ResourceConflictError("Workflow 文档超过引用检查预算")
                try:
                    template = WorkflowGraphTemplate.model_validate_json(
                        path.read_bytes()
                    )
                except ValueError as exc:
                    raise ResourceConflictError(
                        "存在无法校验的 Workflow 文档，不能删除计量资源"
                    ) from exc
                if reference in collect_measurement_references(template):
                    raise ResourceInUseError(
                        "计量资源仍被 Workflow 草稿或发布版本引用",
                        details={"template_id": template.template_id},
                    )
            version_path.replace(tombstone)
            if document.image_object_key is not None:
                self.storage.delete_tree(
                    document.image_object_key.rsplit("/immutable/", 1)[0] + "/immutable"
                )

    def export(self, reference: ResourceReference, *, project_id: str) -> bytes:
        """单资源独立归档，不改变既有 Workflow JSON 导出的语义。"""
        document = self.read(reference, project_id=project_id)
        image = self.image_bytes(document)
        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_STORED) as archive:
            archive.writestr("resource.json", canonical_bytes(document.content))
            if image is not None:
                archive.writestr("reference.png", image)
        return output.getvalue()

    def import_archive(
        self,
        archive_bytes: bytes,
        *,
        project_id: str,
        name: str,
        actor_id: str | None = None,
    ):
        """限制条目、展开大小并验证 CRC/hash；不向磁盘解压客户端路径。"""
        if len(archive_bytes) > _MAX_IMAGE_BYTES + _MAX_DOCUMENT_BYTES:
            raise InvalidRequestError("计量资源包超过 68 MB")
        try:
            with ZipFile(BytesIO(archive_bytes)) as archive:
                entries = archive.infolist()
                names = [e.filename for e in entries]
                if len(names) != len(set(names)) or set(names) not in (
                    {"resource.json"},
                    {"resource.json", "reference.png"},
                ):
                    raise ValueError("资源包条目无效")
                if any(
                    e.file_size
                    > (
                        _MAX_DOCUMENT_BYTES
                        if e.filename == "resource.json"
                        else _MAX_IMAGE_BYTES
                    )
                    for e in entries
                ):
                    raise ValueError("资源包展开大小超限")
                content = MeasurementResourceContent.model_validate_json(
                    archive.read("resource.json")
                )
                image = (
                    archive.read("reference.png") if "reference.png" in names else None
                )
        except (
            ValueError,
            OSError,
            RuntimeError,
            BadZipFile,
            NotImplementedError,
        ) as exc:
            raise InvalidRequestError("计量资源包无效") from exc
        return self.save(
            project_id=project_id,
            name=name,
            content=content,
            image_bytes=image,
            actor_id=actor_id,
        )


class PreparedMeasurementResources:
    """每个 Snapshot 服务的有界只读缓存；无磁盘临时交换、无后台线程。"""

    def __init__(self, storage, *, max_entries=64, max_bytes=256 * 1024 * 1024):
        """初始化准备缓存，容量不足时淘汰未借用的缓存引用。"""
        self.service = MeasurementResourceService(storage)
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = Lock()

    def prepare(self, references, *, project_id: str):
        """原图解码/hash 仅在首次准备时执行；每次都检查项目归属。"""
        prepared = {}
        prepared_bytes = 0
        with self.lock:
            for reference in references:
                if reference.project_id != project_id:
                    raise InvalidRequestError("计量资源不属于当前 Project")
                key = reference_key(reference)
                item = self.entries.get(key)
                if item is None:
                    document = self.service.read(reference, project_id=project_id)
                    expected = document.content.template
                    # PNG 最多 uint16 RGBA；以最坏解码占用预检，禁止先超量分配再报错。
                    if (
                        expected is not None
                        and prepared_bytes
                        + expected.image_width * expected.image_height * 8
                        > self.max_bytes
                    ):
                        raise InvalidRequestError(
                            "本次 Workflow 的参考图超过准备内存预算"
                        )
                    encoded = self.service.image_bytes(document)
                    image = None
                    size = len(canonical_bytes(document.content))
                    if encoded is not None:
                        import cv2
                        import numpy as np

                        image = cv2.imdecode(
                            np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_UNCHANGED
                        )
                        if image is None:
                            raise InvalidRequestError("计量参考图解码失败")
                        image.setflags(write=False)
                        size += image.nbytes
                    if size > self.max_bytes:
                        raise InvalidRequestError("计量资源超过运行时准备内存预算")
                    item = (
                        MappingProxyType({"content": document.content, "image": image}),
                        size,
                    )
                    self.entries[key] = item
                    self.bytes += size
                self.entries.move_to_end(key)
                prepared[key] = item[0]
                prepared_bytes += item[1]
                # 在循环内收敛缓存，不能先加载全部参考图后才检查内存总量。
                while (
                    len(self.entries) > self.max_entries or self.bytes > self.max_bytes
                ):
                    _, (_, size) = self.entries.popitem(last=False)
                    self.bytes -= size
                if prepared_bytes > self.max_bytes:
                    raise InvalidRequestError(
                        "本次 Workflow 的计量资源总量超过准备内存预算"
                    )
            while len(self.entries) > self.max_entries or self.bytes > self.max_bytes:
                _, (_, size) = self.entries.popitem(last=False)
                self.bytes -= size
        return MappingProxyType(prepared)
