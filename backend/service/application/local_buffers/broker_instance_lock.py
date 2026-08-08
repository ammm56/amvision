"""LocalBufferBroker 根目录单实例锁。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO
import json
import os

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.local_buffers.backend_service_process_takeover import (
    build_backend_service_owner_metadata,
)


_LOCK_FILE_NAME = ".local-buffer-broker.lock"


@dataclass
class LocalBufferBrokerInstanceLock:
    """持有一个 LocalBufferBroker 根目录的跨进程独占锁。

    字段：
    - root_dir：broker 管理的 mmap 文件根目录。
    """

    root_dir: Path
    _lock_file: BinaryIO | None = field(default=None, init=False, repr=False)

    @property
    def lock_path(self) -> Path:
        """返回当前根目录的稳定锁文件路径。"""

        return self.root_dir / _LOCK_FILE_NAME

    def acquire(self) -> None:
        """获取独占锁，并记录当前 broker 进程信息。"""

        if self._lock_file is not None:
            return
        resolved_root_dir = self.root_dir.resolve()
        resolved_root_dir.mkdir(parents=True, exist_ok=True)
        lock_path = resolved_root_dir / _LOCK_FILE_NAME
        lock_file = lock_path.open("a+b")
        try:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            try:
                _lock_file_non_blocking(lock_file)
            except (BlockingIOError, OSError) as exc:
                owner = _read_owner_metadata(lock_file)
                owner_process_id = owner.get("process_id")
                owner_supervisor_process_id = owner.get("supervisor_process_id")
                owner_summary = (
                    f"，占用 broker PID={owner_process_id}"
                    f"，supervisor PID={owner_supervisor_process_id}"
                    if owner_process_id is not None
                    else ""
                )
                raise ServiceConfigurationError(
                    "LocalBufferBroker 根目录已被其他进程占用"
                    f"（root_dir={resolved_root_dir}{owner_summary}）",
                    details={
                        "reason": "root-lock-busy",
                        "root_dir": str(resolved_root_dir),
                        "lock_path": str(lock_path),
                        "owner_process_id": owner_process_id,
                        "owner_supervisor_process_id": owner_supervisor_process_id,
                        "owner_service_root_process_id": owner.get(
                            "service_root_process_id"
                        ),
                        "owner_acquired_at": owner.get("acquired_at"),
                        "owner": owner,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc) or type(exc).__name__,
                    },
                ) from exc
            _write_owner_metadata(lock_file, root_dir=resolved_root_dir)
        except Exception:
            lock_file.close()
            raise
        self.root_dir = resolved_root_dir
        self._lock_file = lock_file

    def release(self) -> None:
        """释放独占锁并关闭锁文件。"""

        lock_file = self._lock_file
        self._lock_file = None
        if lock_file is None:
            return
        try:
            lock_file.seek(1)
            lock_file.truncate()
            lock_file.flush()
            _unlock_file(lock_file)
        finally:
            lock_file.close()


def _write_owner_metadata(lock_file: BinaryIO, *, root_dir: Path) -> None:
    """在锁文件首字节之后写入当前占用者信息。"""

    payload = {
        **build_backend_service_owner_metadata(root_dir=root_dir),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }
    encoded_payload = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    lock_file.seek(1)
    lock_file.truncate()
    lock_file.write(encoded_payload)
    lock_file.flush()
    os.fsync(lock_file.fileno())


def _read_owner_metadata(lock_file: BinaryIO) -> dict[str, object]:
    """最佳努力读取当前锁占用者信息。"""

    try:
        lock_file.seek(1)
        payload = json.loads(lock_file.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _lock_file_non_blocking(lock_file: BinaryIO) -> None:
    """跨平台尝试获取锁文件首字节的独占锁。"""

    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(lock_file: BinaryIO) -> None:
    """释放锁文件首字节的独占锁。"""

    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
