"""Windows extended-length path 辅助。"""

from __future__ import annotations

import os
from pathlib import Path


def to_filesystem_path(path: Path) -> Path:
    """在 Windows 上返回不受传统 MAX_PATH 限制的绝对路径。"""

    if os.name != "nt":
        return path
    raw_path = os.path.abspath(os.fspath(path))
    if raw_path.startswith("\\\\?\\"):
        return Path(raw_path)
    if raw_path.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{raw_path[2:]}")
    return Path(f"\\\\?\\{raw_path}")
