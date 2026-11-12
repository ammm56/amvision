"""固定数据集版本的只读文件浏览，不接受任意磁盘路径。"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
)
from backend.service.infrastructure.filesystem.shared_files import open_shared_read


def version_file(root: Path, relative_path: str) -> Path:
    """校验相对路径及链接目标始终位于当前版本内。"""
    relative = PurePosixPath(relative_path.replace("\\", "/"))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or ":" in relative_path
        or "\x00" in relative_path
    ):
        raise InvalidRequestError("文件路径无效")
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if not path.is_relative_to(resolved_root):
        raise InvalidRequestError("文件不属于当前数据集版本")
    if not path.exists():
        raise ResourceNotFoundError("文件已移除或不可用")
    return path


def list_version_files(
    root: Path,
    relative_path: str,
    *,
    after: str,
    limit: int,
    directories_only: bool = False,
) -> dict:
    """仅列一层目录；游标按名称稳定分页，不递归扫描或加载文件内容。"""
    import heapq

    folder = version_file(root, relative_path)
    if not folder.is_dir():
        raise InvalidRequestError("请选择文件夹")
    # 内存只保留一页。用名称游标避免依赖文件系统枚举顺序。
    with os.scandir(folder) as entries:
        names = heapq.nsmallest(
            limit + 1,
            (
                entry.name
                for entry in entries
                if entry.name > after
                and not entry.is_symlink()
                and (not directories_only or entry.is_dir(follow_symlinks=False))
            ),
        )
    has_more = len(names) > limit
    result = []
    for name in names[:limit]:
        relative = str(PurePosixPath(relative_path) / name)
        try:
            path = version_file(root, relative)
            stat = path.stat()
        except (OSError, ResourceNotFoundError, InvalidRequestError):
            continue
        has_directories = None
        has_children = None
        if path.is_dir():
            try:
                with os.scandir(path) as children:
                    if directories_only:
                        has_directories = any(
                            child.is_dir(follow_symlinks=False) and not child.is_symlink()
                            for child in children
                        )
                    else:
                        # 文件树只判断有没有可见子项，遇到第一项即停止，不递归扫描。
                        has_children = any(not child.is_symlink() for child in children)
            except OSError:
                pass  # 无法探测时保留展开入口，由实际读取给出错误。
        result.append(
            {
                "name": name,
                "path": relative,
                "directory": path.is_dir(),
                "size": None if path.is_dir() else stat.st_size,
                "has_directories": has_directories,
                "has_children": has_children,
            }
        )
    return {
        "items": result,
        "path": relative_path,
        "next_cursor": names[limit - 1] if has_more else None,
    }


def read_version_text(root: Path, relative_path: str) -> dict:
    """仅预览文本文件前 256 KiB；大文件不在请求中完整解析。"""
    path = version_file(root, relative_path)
    if not path.is_file() or path.suffix.lower() not in {
        ".json",
        ".jsonl",
        ".txt",
        ".yaml",
        ".yml",
        ".xml",
        ".csv",
    }:
        raise InvalidRequestError("此文件不支持文本预览")
    with open_shared_read(path) as stream:
        data = stream.read(262145)
    return {
        "path": relative_path,
        "content": data[:262144].decode("utf-8-sig", errors="replace"),
        "truncated": len(data) > 262144,
    }
