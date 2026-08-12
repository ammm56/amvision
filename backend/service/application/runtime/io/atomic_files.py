"""同目录临时文件与原子替换 helper。"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def atomic_write_bytes(
    path: Path,
    content: bytes,
    *,
    overwrite: bool = True,
) -> None:
    """把完整字节原子写入目标路径。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise FileExistsError(str(path))
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if not overwrite and path.exists():
            raise FileExistsError(str(path))
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    """在支持目录 fsync 的平台持久化目录项。"""

    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["atomic_write_bytes"]
