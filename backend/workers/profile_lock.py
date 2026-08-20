"""backend-worker Profile 进程单实例锁。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import BinaryIO


class BackendWorkerProfileLock:
    """持有一个 Topology epoch/Profile 对应的跨进程排他文件锁。"""

    def __init__(self, *, lock_path: Path, owner: dict[str, object]) -> None:
        """初始化 Profile 单实例锁。"""

        self.lock_path = lock_path
        self.owner = owner
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        """非阻塞获取排他锁；同 Profile 已运行时立即失败。"""

        if self._handle is not None:
            raise RuntimeError("backend-worker Profile 锁已经持有")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        if self.lock_path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            _lock_file(handle)
        except OSError as error:
            handle.close()
            raise RuntimeError(
                f"backend-worker Profile 已有运行实例: {self.lock_path}"
            ) from error
        handle.seek(0)
        handle.truncate()
        handle.write(
            (
                json.dumps(
                    {**self.owner, "process_id": os.getpid()},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle

    def release(self) -> None:
        """释放排他锁并关闭文件句柄。"""

        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _unlock_file(handle)
        finally:
            handle.close()

    def __enter__(self) -> BackendWorkerProfileLock:
        """获取锁并返回自身。"""

        self.acquire()
        return self

    def __exit__(
        self, _exc_type: object, _exc_value: object, _traceback: object
    ) -> None:
        """退出上下文时释放锁。"""

        self.release()


def _lock_file(handle: BinaryIO) -> None:
    """按当前平台非阻塞获取一个字节的文件锁。"""

    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    """按当前平台释放文件锁。"""

    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
