"""导入向导的短期 ZIP。上传与创建版本分开，草稿由项目和登录主体共同拥有。"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import time
from typing import BinaryIO, Iterator
from uuid import UUID, uuid4

from backend.service.application.datasets.content import content_access
from backend.service.application.workflows.documents.storage import normalize_identifier
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class UploadDraft:
    """单次上传的回执，文件系统路径始终留在服务内。"""

    draft_id: str
    name: str
    size: int


class DatasetUploadDrafts:
    """受管存储中的短期文件；以原子重命名保证每个草稿至多被提交一次。"""

    ttl_seconds = 24 * 3600

    def __init__(self, storage: LocalDatasetStorage, project: str, principal: str):
        project = normalize_identifier(project, "project_id")
        owner = sha256(principal.encode()).hexdigest()
        self.storage = storage
        self.prefix = f"projects/{project}/dataset-upload-drafts/{owner}"
        self.root = storage.resolve(self.prefix)

    def _path(self, token: UUID) -> Path:
        return self.root / token.hex

    def prune(self) -> None:
        """操作前复用全局维护使用的同一回收逻辑；活动所有者直接跳过。"""
        from .upload_draft_cleanup import prune_owner

        prune_owner(self.storage, self.prefix, cutoff=time() - self.ttl_seconds)

    def access(self):
        """持有已有跨进程共享句柄锁，阻止维护清理，不阻止同一用户并行上传。"""
        return content_access(self.storage, f"upload-drafts:{self.prefix}")

    def upload(self, name: str, stream: BinaryIO) -> UploadDraft:
        """分块保存 ZIP；写入未完成前不会发给调用者可用回执。"""
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        if not name.lower().endswith(".zip") or len(name) > 255:
            raise InvalidRequestError("请选择 ZIP 文件")
        self.prune()
        token = uuid4()
        path = self._path(token)
        with self.access():
            try:
                size = self.storage.write_stream(
                    f"{self.prefix}/{token.hex}",
                    stream,
                    max_bytes=self.storage.settings.max_import_package_bytes,
                )
                if not size:
                    raise InvalidRequestError("ZIP 文件为空")
                self.storage.write_json(
                    f"{self.prefix}/{token.hex}.json", {"name": name}
                )
                return UploadDraft(token.hex, name, size)
            except BaseException:
                path.unlink(missing_ok=True)
                path.with_suffix(".json").unlink(missing_ok=True)
                raise

    def discard(self, token: UUID) -> None:
        """撤销未提交的文件；已消费的回执可重复撤销。"""
        path = self._path(token)
        with self.access():
            try:
                path.unlink()
            except FileNotFoundError:
                return
            path.with_suffix(".json").unlink(missing_ok=True)

    @contextmanager
    def consume(self, token: UUID) -> Iterator[tuple[str, BinaryIO]]:
        """原子领取 ZIP；失败归还，成功释放文件。"""
        self.prune()
        path = self._path(token)
        claimed = path.with_suffix(".submitting")
        with self.access():
            try:
                # 回收冲突不会延长有效期；仍须在领取时检查文件本身。
                if time() - path.stat().st_mtime > self.ttl_seconds:
                    raise FileNotFoundError(path)
                path.rename(claimed)
            except FileNotFoundError as error:
                raise ResourceNotFoundError(
                    "上传文件已过期、已提交或不存在，请重新选择 ZIP",
                    details={"resource": "upload_draft"},
                ) from error
            try:
                name = json.loads(
                    path.with_suffix(".json").read_text(encoding="utf-8")
                )["name"]
                with claimed.open("rb") as stream:
                    yield name, stream
            except BaseException:
                claimed.rename(path)
                raise
            else:
                for finished in (claimed, path.with_suffix(".json")):
                    try:
                        finished.unlink(missing_ok=True)
                    except PermissionError:
                        pass  # 提交已完成，由维护回收锁保护下的残留文件。
