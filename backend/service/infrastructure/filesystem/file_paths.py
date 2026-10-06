"""解析稳定文件位置，不把原子替换中的旧文件身份当成目标路径。"""

import errno
import os
from pathlib import Path


def resolve_file_location(path: Path) -> Path:
    """解析父目录及显式符号链接，普通文件始终保留配置的目录项名称。

    Windows 的 GetFinalPathNameByHandle 在并发 POSIX 替换时可能返回
    $Extend/$Deleted 下的旧文件名，因此不能对普通文件调用 Path.resolve。
    链接最多解析 40 层；正常路径不增加锁、等待或重试。
    """
    current = Path(os.path.abspath(path.expanduser()))
    for _ in range(40):
        if not current.name:
            return current.resolve()
        current = current.parent.resolve() / current.name
        if not current.is_symlink():
            return current
        target = Path(os.readlink(current))
        current = Path(os.path.abspath(current.parent / target))
    raise OSError(errno.ELOOP, "文件路径的符号链接层数过多", str(path))
