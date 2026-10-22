"""受管跨进程临时输入；最后一个 OS 句柄关闭后回收，不留下崩溃暂存文件。"""

from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile

from backend.service.infrastructure.filesystem.shared_files import open_shared_read


class SharedTemporaryInput:
    """Windows 使用 delete-on-close，Ubuntu 使用匿名文件的只读 procfd 入口。

    path 仅经私有 worker 通道交接；业务层不解析平台路径或句柄。
    """

    def __init__(self, root: Path):
        """root 来自服务运行数据目录，Ubuntu 必须位于原生文件系统。"""
        root.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            self.stream = tempfile.NamedTemporaryFile(
                dir=root, prefix="preview-", delete=True
            )
            self.path = str(self.stream.name)
        elif sys.platform == "linux":
            self.stream = tempfile.TemporaryFile(dir=root)
            self.path = f"/proc/{os.getpid()}/fd/{self.stream.fileno()}"
        else:
            raise RuntimeError("Preview 文件快照当前仅验收 Windows 和 Ubuntu")
        self.sealed = False

    def write(self, content):
        """发布后永久禁止本 owner 继续写入。"""
        if self.sealed:
            raise ValueError("preview_input_already_committed")
        if self.stream.write(content) != len(content):
            raise OSError("preview_input_short_write")

    def seal(self):
        """刷新并固定 OS 文件身份，PID/fd 重用不能命中另一份文件。"""
        if self.sealed:
            raise ValueError("preview_input_already_committed")
        self.stream.flush()
        stat = os.fstat(self.stream.fileno())
        self.sealed = True
        return {
            "path": self.path,
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "size": stat.st_size,
        }

    def close(self):
        """仅在 worker pin 归还或进程确认退出后调用。"""
        self.stream.close()


@contextmanager
def open_temporary_input(identity):
    """打开同一份快照；进程退出、句柄复用或文件替换均明确失败。"""
    with open_shared_read(Path(identity["path"])) as stream:
        stat = os.fstat(stream.fileno())
        if (stat.st_dev, stat.st_ino, stat.st_size) != (
            identity["device"],
            identity["inode"],
            identity["size"],
        ):
            raise ValueError("preview_input_snapshot_changed")
        yield stream
