"""本机文件系统保留清理使用的流式扫描和条件删除。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
import os
from pathlib import Path, PurePosixPath
import stat

from backend.service.application.ports.object_store import (
    RetentionDeleteState,
    RetentionObjectMetadata,
    RetentionObjectPage,
)
from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path
from backend.service.infrastructure.filesystem.directory_guard import (
    UnsafeDirectoryError,
    delete_windows_file_if_unchanged,
    protect_child_directory,
    protect_directory,
    remove_empty_directory,
)


_WINDOWS_REPARSE_POINT = 0x0400


def iter_local_retention_pages(
    target_root: Path,
    *,
    recursive: bool,
    page_size: int,
    object_key_prefix: str = "",
    checkpoint: Callable[[], None] = lambda: None,
) -> Iterator[RetentionObjectPage]:
    """分页流式列举目标目录中的普通稳定文件。"""

    if page_size <= 0:
        raise ValueError("page_size 必须大于 0")
    logical_root = Path(os.path.abspath(target_root))
    filesystem_root = to_filesystem_path(logical_root)
    if not filesystem_root.is_dir():
        return

    page_items: list[RetentionObjectMetadata] = []
    with _safe_walk(logical_root, recursive=recursive, checkpoint=checkpoint) as walk:
        for directory_path, entry in walk:
            if entry is None:
                continue
            if _is_control_name(entry.name):
                continue
            entry_path = directory_path / entry.name
            try:
                # 扫描阶段复用 DirEntry 缓存，避免为每个文件再次打开路径。
                entry_stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if _is_reparse_or_symlink(entry_stat):
                continue
            if stat.S_ISDIR(entry_stat.st_mode):
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                continue
            try:
                # Windows 的 DirEntry.stat().st_ino 为 0，inode() 才返回真实文件 ID。
                # 防止同尺寸、同时间戳的替换文件被当作扫描时的原文件。
                file_id = entry.inode()
            except FileNotFoundError:
                continue
            relative_key = entry_path.relative_to(logical_root).as_posix()
            object_key = _join_object_key(object_key_prefix, relative_key)
            page_items.append(
                RetentionObjectMetadata(
                    object_key=object_key,
                    content_length=int(entry_stat.st_size),
                    last_modified_epoch_ns=_mtime_ns(entry_stat),
                    version=_build_local_file_version(entry_stat, file_id=file_id),
                )
            )
            if len(page_items) >= page_size:
                yield RetentionObjectPage(items=tuple(page_items))
                page_items.clear()
    if page_items:
        yield RetentionObjectPage(items=tuple(page_items))


def delete_local_retention_file_if_version(
    target_path: Path,
    *,
    expected_version: str,
    protected_root: Path | None = None,
) -> RetentionDeleteState:
    """只在本机文件仍是扫描版本时删除。"""

    try:
        with protect_directory(target_path.parent, protected_root=protected_root):
            return _delete_guarded_file(target_path, expected_version=expected_version)
    except FileNotFoundError:
        return "missing"
    except UnsafeDirectoryError:
        return "changed"


def _delete_guarded_file(
    target_path: Path, *, expected_version: str
) -> RetentionDeleteState:
    """父目录已保护时重检并删除文件。"""
    if os.name == "nt":
        return delete_windows_file_if_unchanged(
            target_path,
            lambda observed: _build_local_file_version(observed) == expected_version,
        )
    filesystem_path = to_filesystem_path(target_path)
    try:
        current_stat = filesystem_path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return "missing"
    if _is_reparse_or_symlink(current_stat) or not stat.S_ISREG(current_stat.st_mode):
        return "changed"
    if _build_local_file_version(current_stat) != expected_version:
        return "changed"
    try:
        filesystem_path.unlink()
    except FileNotFoundError:
        return "missing"
    except PermissionError as error:
        if getattr(error, "winerror", None) in {32, 33}:
            return "locked"
        raise
    return "deleted"


def delete_empty_local_retention_directories(
    target_root: Path,
    *,
    recursive: bool,
    checkpoint: Callable[[], None] = lambda: None,
) -> int:
    """自底向上删除空子目录，并保留目标根目录。"""

    if not recursive:
        return 0
    logical_root = Path(os.path.abspath(target_root))
    filesystem_root = to_filesystem_path(logical_root)
    if not filesystem_root.is_dir():
        return 0
    removed_count = 0
    with _safe_walk(logical_root, recursive=True, checkpoint=checkpoint) as walk:
        for current, entry in walk:
            if entry is None and current != logical_root:
                checkpoint()
                removed_count += int(remove_empty_directory(current))
    return removed_count


class _safe_walk:
    """显式 DFS；进入前过滤，退出前释放本层句柄，保持父目录保护。"""

    def __init__(self, root: Path, *, recursive: bool, checkpoint: Callable[[], None]):
        self.root, self.recursive, self.checkpoint = root, recursive, checkpoint
        self.frames: list[tuple[Path, object, ExitStack]] = []

    def _enter(self, path: Path) -> None:
        """只进入无链接的目录，句柄和 scandir 同生命周期。"""
        resources = ExitStack()
        try:
            resources.enter_context(
                protect_child_directory(path)
                if self.frames
                else protect_directory(path)
            )
            entries = resources.enter_context(os.scandir(to_filesystem_path(path)))
        except FileNotFoundError:
            resources.close()
            return
        except UnsafeDirectoryError:
            resources.close()
            if path == self.root:
                raise
            return
        except BaseException:
            resources.close()
            raise
        self.frames.append((path, entries, resources))

    def __enter__(self):
        self._enter(self.root)
        return self

    def __iter__(self):
        while self.frames:
            self.checkpoint()
            path, entries, resources = self.frames[-1]
            entry = next(entries, None)
            if entry is None:
                self.frames.pop()
                resources.close()
                yield path, None
                continue
            if _is_control_name(entry.name):
                continue
            try:
                observed = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if _is_reparse_or_symlink(observed):
                continue
            if stat.S_ISDIR(observed.st_mode):
                if self.recursive:
                    self._enter(path / entry.name)
            else:
                yield path, entry

    def __exit__(self, *exc):
        while self.frames:
            self.frames.pop()[2].close()


def _join_object_key(prefix: str, relative_key: str) -> str:
    """连接可选 ObjectStore prefix 与相对文件 key。"""

    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        return PurePosixPath(relative_key).as_posix()
    return (PurePosixPath(normalized_prefix) / relative_key).as_posix()


def _is_control_name(name: str) -> bool:
    """识别不允许被生产结果清理节点处理的内部控制项。"""

    normalized_name = name.casefold()
    return normalized_name.startswith(".amvision-") or (
        normalized_name.startswith(".") and normalized_name.endswith(".tmp")
    )


def _is_reparse_or_symlink(file_stat: os.stat_result) -> bool:
    """识别符号链接和 Windows reparse point。"""

    if stat.S_ISLNK(file_stat.st_mode):
        return True
    return bool(
        int(getattr(file_stat, "st_file_attributes", 0)) & _WINDOWS_REPARSE_POINT
    )


def _build_local_file_version(
    file_stat: os.stat_result, *, file_id: int | None = None
) -> str:
    """构造足以识别本机文件替换和修改的版本标识。"""

    if os.name == "nt":
        values = (
            int(file_stat.st_ino if file_id is None else file_id),
            int(file_stat.st_size),
            _mtime_ns(file_stat),
            _ctime_ns(file_stat),
        )
    else:
        values = (
            int(getattr(file_stat, "st_dev", 0)),
            int(getattr(file_stat, "st_ino", 0)),
            int(file_stat.st_size),
            _mtime_ns(file_stat),
            _ctime_ns(file_stat),
        )
    return ":".join(str(value) for value in values)


def _mtime_ns(file_stat: os.stat_result) -> int:
    """跨 Python/平台读取纳秒修改时间。"""

    return int(
        getattr(
            file_stat,
            "st_mtime_ns",
            round(float(file_stat.st_mtime) * 1_000_000_000),
        )
    )


def _ctime_ns(file_stat: os.stat_result) -> int:
    """读取文件元数据变化时间，Windows 上用于识别同尺寸文件替换。"""

    return int(
        getattr(
            file_stat,
            "st_ctime_ns",
            round(float(file_stat.st_ctime) * 1_000_000_000),
        )
    )


__all__ = [
    "delete_empty_local_retention_directories",
    "delete_local_retention_file_if_version",
    "iter_local_retention_pages",
]
