"""同目录临时文件与原子替换 helper。"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from backend.service.infrastructure.filesystem.atomic_files import (
    publish_path_without_overwrite,
)
from backend.service.infrastructure.filesystem.shared_files import replace_shared_file


def atomic_write_bytes(
    path: Path,
    content: bytes,
    *,
    overwrite: bool = True,
) -> None:
    """把完整字节原子写入目标路径。"""

    temporary_path: Path | None = None
    failure: OSError | None = None
    stage = "create_directory"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not overwrite and path.exists():
            raise FileExistsError(str(path))
        stage = "create_temporary"
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            stage = "write_temporary"
            temporary_file.write(content)
            stage = "flush_temporary"
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        stage = "replace"
        if overwrite:
            replace_shared_file(temporary_path, path)
        elif not publish_path_without_overwrite(temporary_path, path):
            raise FileExistsError(str(path))
        temporary_path = None
        stage = "flush_directory"
        _fsync_directory(path.parent)
    except OSError as error:
        failure = error
        # 保留原始异常类型和 WinError，节点边界据此输出可操作的诊断。
        error.file_io_stage = stage
        error.file_io_path = str(path)
        raise
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                if failure is None:
                    raise
                # 清理失败不能覆盖最初的写入错误，也不能把失败报告成成功。
                failure.file_io_cleanup_error = str(cleanup_error)
                failure.add_note(f"临时文件清理失败：{cleanup_error}")


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
