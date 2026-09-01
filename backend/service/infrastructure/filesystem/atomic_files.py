"""本地文件原子替换与 Windows 短暂占用恢复。"""

from __future__ import annotations

import os
from pathlib import Path
from time import monotonic, sleep


_TRANSIENT_WINDOWS_FILE_ERROR_CODES = frozenset({5, 32, 33})


def replace_path_with_retry(
    source_path: Path,
    target_path: Path,
    *,
    retry_timeout_seconds: float = 2.0,
) -> None:
    """原子替换路径，并对 Windows sharing violation 做有界退避重试。

    参数：
    - source_path：同文件系统上的临时源路径。
    - target_path：需要原子替换的目标路径。
    - retry_timeout_seconds：Windows 短暂占用的最大重试预算。
    """

    deadline = monotonic() + max(0.0, float(retry_timeout_seconds))
    retry_interval_seconds = 0.005
    while True:
        try:
            source_path.replace(target_path)
            return
        except PermissionError as error:
            if (
                getattr(error, "winerror", None)
                not in _TRANSIENT_WINDOWS_FILE_ERROR_CODES
                or monotonic() >= deadline
            ):
                raise
            sleep(retry_interval_seconds)
            retry_interval_seconds = min(retry_interval_seconds * 2.0, 0.1)


def publish_path_without_overwrite(source_path: Path, target_path: Path) -> bool:
    """把完整临时文件原子发布为新文件，目标已存在时不覆盖。

    参数：
    - source_path：与目标位于同一文件系统、已经完整写入并 fsync 的临时文件。
    - target_path：需要创建的最终路径。

    返回：
    - bool：成功创建目标时为 ``True``；目标已经存在时为 ``False``。

    Windows 的 rename 不覆盖既有目标；POSIX rename 会覆盖，因此使用 hard link
    原子创建目录项，再移除临时文件。两个分支都不会暴露半截目标文件。
    """

    if os.name == "nt":
        try:
            source_path.rename(target_path)
        except FileExistsError:
            return False
        return True

    try:
        os.link(source_path, target_path)
    except FileExistsError:
        return False
    source_path.unlink()
    return True
