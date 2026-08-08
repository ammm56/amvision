"""本地文件原子替换与 Windows 短暂占用恢复。"""

from __future__ import annotations

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
