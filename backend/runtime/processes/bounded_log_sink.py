"""持续排空进程输出时使用的有界日志保留器。"""

from __future__ import annotations

from collections import deque
import contextlib
from pathlib import Path
from threading import Lock
from typing import BinaryIO


class BoundedByteTail:
    """线程安全地保留日志末尾固定字节数。"""

    def __init__(self, capacity_bytes: int) -> None:
        self.capacity_bytes = max(1024, int(capacity_bytes))
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._lock = Lock()

    def append(self, chunk: bytes) -> None:
        """追加日志块并丢弃超出容量的最早内容。"""

        with self._lock:
            self._chunks.append(chunk)
            self._size += len(chunk)
            while self._size > self.capacity_bytes and self._chunks:
                excess = self._size - self.capacity_bytes
                head = self._chunks[0]
                if len(head) <= excess:
                    self._chunks.popleft()
                    self._size -= len(head)
                    continue
                self._chunks[0] = head[excess:]
                self._size -= excess

    def decode(self) -> str:
        """把当前 tail 解码为 UTF-8 文本。"""

        with self._lock:
            payload = b"".join(self._chunks)
        return payload.decode("utf-8", errors="replace")


class BoundedLogSink:
    """最多保留固定字节数，写入失败后仍允许调用方继续 drain。"""

    def __init__(self, path: Path | None, *, capacity_bytes: int) -> None:
        self.path = path
        self.capacity_bytes = max(0, int(capacity_bytes))
        self.error: str | None = None
        self._stream: BinaryIO | None = None
        self._retained_size = 0
        self._disabled = path is None or self.capacity_bytes == 0

    def open(self) -> None:
        """打开追加文件；失败时只禁用文件保留，不阻断 pipe 排空。"""

        if self._disabled or self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existing_size = self.path.stat().st_size if self.path.exists() else 0
            self._retained_size = min(existing_size, self.capacity_bytes)
            if existing_size >= self.capacity_bytes:
                self._disabled = True
                return
            self._stream = self.path.open("ab", buffering=0)
        except OSError as error:
            self.error = str(error)
            self._disabled = True

    def write(self, chunk: bytes) -> None:
        """在剩余容量内保留日志；超限部分直接丢弃。"""

        if self._disabled or self._stream is None:
            return
        remaining = self.capacity_bytes - self._retained_size
        if remaining <= 0:
            self.close()
            self._disabled = True
            return
        payload = chunk[:remaining]
        try:
            self._stream.write(payload)
            self._retained_size += len(payload)
        except OSError as error:
            self.error = str(error)
            self.close()
            self._disabled = True
            return
        if self._retained_size >= self.capacity_bytes:
            self.close()
            self._disabled = True

    def close(self) -> None:
        """关闭当前日志文件。"""

        stream = self._stream
        self._stream = None
        if stream is not None:
            with contextlib.suppress(OSError):
                stream.close()


__all__ = ["BoundedByteTail", "BoundedLogSink"]
