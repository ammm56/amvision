"""本机文件系统保留清理使用的流式扫描和条件删除。"""

from __future__ import annotations

from collections.abc import Iterator
import errno
import os
from pathlib import Path, PurePosixPath
import stat

from backend.service.application.ports.object_store import (
    RetentionDeleteState,
    RetentionObjectMetadata,
    RetentionObjectPage,
)
from backend.service.infrastructure.filesystem.windows_paths import to_filesystem_path


_WINDOWS_REPARSE_POINT = 0x0400


def iter_local_retention_pages(
    target_root: Path,
    *,
    recursive: bool,
    page_size: int,
    object_key_prefix: str = "",
) -> Iterator[RetentionObjectPage]:
    """分页流式列举目标目录中的普通稳定文件。"""

    if page_size <= 0:
        raise ValueError("page_size 必须大于 0")
    logical_root = target_root.resolve(strict=False)
    filesystem_root = to_filesystem_path(logical_root)
    if not filesystem_root.is_dir():
        return

    page_items: list[RetentionObjectMetadata] = []
    directory_stack = [logical_root]
    while directory_stack:
        directory_path = directory_stack.pop()
        try:
            with os.scandir(to_filesystem_path(directory_path)) as entries:
                for entry in entries:
                    if _is_control_name(entry.name):
                        continue
                    entry_path = directory_path / entry.name
                    try:
                        # 扫描阶段复用 DirEntry 缓存，避免为每个文件再次打开路径。
                        # Windows 版本标识不依赖部分路径下可能为 0 的 inode。
                        entry_stat = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if _is_reparse_or_symlink(entry_stat):
                        continue
                    if stat.S_ISDIR(entry_stat.st_mode):
                        if recursive:
                            directory_stack.append(entry_path)
                        continue
                    if not stat.S_ISREG(entry_stat.st_mode):
                        continue
                    relative_key = entry_path.relative_to(logical_root).as_posix()
                    object_key = _join_object_key(object_key_prefix, relative_key)
                    page_items.append(
                        RetentionObjectMetadata(
                            object_key=object_key,
                            content_length=int(entry_stat.st_size),
                            last_modified_epoch_ns=_mtime_ns(entry_stat),
                            version=_build_local_file_version(entry_stat),
                        )
                    )
                    if len(page_items) >= page_size:
                        yield RetentionObjectPage(items=tuple(page_items))
                        page_items.clear()
        except FileNotFoundError:
            continue
    if page_items:
        yield RetentionObjectPage(items=tuple(page_items))


def delete_local_retention_file_if_version(
    target_path: Path,
    *,
    expected_version: str,
) -> RetentionDeleteState:
    """只在本机文件仍是扫描版本时删除。"""

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
) -> int:
    """自底向上删除空子目录，并保留目标根目录。"""

    if not recursive:
        return 0
    logical_root = target_root.resolve(strict=False)
    filesystem_root = to_filesystem_path(logical_root)
    if not filesystem_root.is_dir():
        return 0
    removed_count = 0
    for current_path, directory_names, _file_names in os.walk(
        filesystem_root,
        topdown=False,
        onerror=_raise_os_error,
        followlinks=False,
    ):
        current = Path(current_path)
        if current == filesystem_root:
            continue
        if _is_control_name(current.name):
            continue
        try:
            current_stat = current.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if _is_reparse_or_symlink(current_stat):
            continue
        # os.walk 不跟随链接；再次枚举可避免并发写入期间误删非空目录。
        try:
            next(current.iterdir())
        except StopIteration:
            try:
                current.rmdir()
            except FileNotFoundError:
                continue
            except OSError as error:
                if error.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                    continue
                raise
            removed_count += 1
        except FileNotFoundError:
            continue
    return removed_count


def _join_object_key(prefix: str, relative_key: str) -> str:
    """连接可选 ObjectStore prefix 与相对文件 key。"""

    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        return PurePosixPath(relative_key).as_posix()
    return (PurePosixPath(normalized_prefix) / relative_key).as_posix()


def _raise_os_error(error: OSError) -> None:
    """让目录扫描权限和 I/O 错误进入节点结构化失败路径。"""

    raise error


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


def _build_local_file_version(file_stat: os.stat_result) -> str:
    """构造足以识别本机文件替换和修改的版本标识。"""

    if os.name == "nt":
        values = (
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
    return ":".join(
        str(value)
        for value in values
    )


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
