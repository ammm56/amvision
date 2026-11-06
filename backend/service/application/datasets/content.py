"""当前版本样本更新：文件先写完整，数据库一次切换；版本号不变。"""

from contextlib import contextmanager
from hashlib import sha256
import errno
import os
import re

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceConflictError,
)
from backend.service.infrastructure.filesystem.native_locks import (
    change_posix_lock,
    change_windows_lock,
)


def content_key(project_id, dataset_id, version_id, metadata=None):
    """返回登记的内容目录；已存在的数据无需搬迁即可继续读取。"""
    root = f"projects/{project_id}/datasets/{dataset_id}/versions/{version_id}"
    revision = (metadata or {}).get("content_revision", "")
    if revision and not re.fullmatch(r"[a-f0-9]{32}", revision):
        raise InvalidRequestError("数据集内容标识无效")
    return f"{root}/contents/{revision}" if revision else root


@contextmanager
def content_access(storage, version_id, *, write=False):
    """文件句柄共享读、排他写；冲突立即返回，进程退出由系统释放。"""
    key = sha256(version_id.encode()).hexdigest()
    path = storage.resolve(f".dataset-locks/{key}.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    change = change_windows_lock if os.name == "nt" else change_posix_lock
    with path.open("a+b") as handle:
        try:
            change(handle, offset=0, shared=not write)
        except OSError as error:
            if getattr(error, "winerror", None) in {32, 33, 158} or error.errno in {
                errno.EACCES,
                errno.EAGAIN,
            }:
                raise ResourceConflictError(
                    "当前版本正在读取或更新，请稍后再操作"
                ) from error
            raise
        try:
            yield
        finally:
            change(handle, offset=0, unlock=True)


def require_revision(current, expected):
    """拒绝覆盖提交之后发生的样本修改。"""
    if current is None or current.metadata.get("content_revision", "") != expected:
        raise ResourceConflictError("当前版本的样本已变化，请刷新后重新操作")


def obsolete_content(source, storage):
    """记录切换后可清理的旧内容；删除失败可在下次修改时继续处理。"""
    old = content_key(
        source.project_id, source.dataset_id, source.dataset_version_id, source.metadata
    )
    paths = (
        [old]
        if source.metadata.get("content_revision")
        else [f"{old}/{name}" for name in ("images", "samples", "indexes", "manifests")]
    )
    previous = [
        key
        for key in source.metadata.get("obsolete_content", [])
        if storage.resolve(key).exists()
    ]
    return list(dict.fromkeys([*previous, *paths]))


def cleanup_content(storage, version):
    """仅在排他提交完成后清理旧目录；失败不反转已完成的数据修改。"""
    root = storage.resolve(
        content_key(version.project_id, version.dataset_id, version.dataset_version_id)
    ).resolve()
    current = storage.resolve(
        content_key(
            version.project_id,
            version.dataset_id,
            version.dataset_version_id,
            version.metadata,
        )
    ).resolve()
    for key in version.metadata.get("obsolete_content", []):
        path = storage.resolve(key).resolve()
        if (
            path == root
            or not path.is_relative_to(root)
            or path == current
            or current.is_relative_to(path)
        ):
            raise InvalidRequestError("旧数据清理路径无效")
        try:
            storage.delete_tree(key)
        except OSError:
            # 保留受管目录记录，下次修改再次清理；不能误报样本更新失败。
            continue
