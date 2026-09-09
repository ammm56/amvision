"""Preview 的有界 OS shared memory；不创建文件支持的 mmap 或临时文件。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from multiprocessing.shared_memory import SharedMemory
from threading import RLock
from time import monotonic
from typing import Iterator
from uuid import uuid4

from backend.contracts.workflows.preview_session import PREVIEW_CHUNK_SIZE


class PreviewMemoryError(ValueError):
    """容量、失效或上传格式错误；禁止写盘降级。"""


@dataclass
class _Block:
    """每块只归一个 session 所有，借用结束前不能关闭映射。"""

    memory: SharedMemory
    owner: str
    size: int
    media_type: str
    digest: str | None
    written: int = 0
    next_index: int = 0
    ready: bool = False
    pins: int = 0
    retiring: bool = False
    touched: float = 0
    file_name: str = "input"
    upload: bool = True


class PreviewBuffers:
    """统一分配/发布/借用/释放；总容量和单会话容量同时受限。"""

    def __init__(self, *, session_limit: int = 512 * 1024**2, total_limit: int = 1024**3):
        """限额只覆盖受管字节，不伪称限制第三方算法 RSS 或 GPU 工作区。"""
        if session_limit <= 0 or total_limit < session_limit:
            raise ValueError("preview_memory_limits_invalid")
        self.session_limit = session_limit
        self.total_limit = total_limit
        self._blocks: dict[str, _Block] = {}
        self._reservations: dict[tuple[str, str], int] = {}
        self._lock = RLock()
        self._closed = False
        self.require_registered_owner = False
        self._owners: set[str] = set()

    def register_owner(self, owner: str) -> None:
        """会话装配启用严格所有权；撤销后禁止竞态中的新分配。"""
        with self._lock:
            self._owners.add(owner)

    def allocate(self, owner: str, size: int, *, media_type: str, digest: str | None = None, file_name: str = "input") -> str:
        """先计量再分配；内存失败不创建登记，不接受客户端 SHM 名称。"""
        with self._lock:
            if self._closed or not owner or size <= 0 or self.require_registered_owner and owner not in self._owners:
                raise PreviewMemoryError("preview_memory_unavailable")
            if len(self._blocks) >= 8192 or sum(block.owner == owner for block in self._blocks.values()) >= 4096:
                raise PreviewMemoryError("preview_memory_block_capacity")
            self._check_capacity(owner, size)
            block_id = uuid4().hex
            memory = SharedMemory(create=True, size=size)
            self._blocks[block_id] = _Block(memory, owner, size, media_type, digest, touched=monotonic(), file_name=file_name)
            return block_id

    def _check_capacity(self, owner: str, additional: int) -> None:
        """SHM、控制状态与 Worker 受管副本共用同一字节预算。"""
        own = sum(b.size for b in self._blocks.values() if b.owner == owner)
        own += sum(size for (account, _), size in self._reservations.items() if account == owner)
        total = sum(b.size for b in self._blocks.values()) + sum(self._reservations.values())
        if own + additional > self.session_limit or total + additional > self.total_limit:
            raise PreviewMemoryError("preview_memory_capacity")

    def reserve(self, owner: str, key: str, size: int) -> None:
        """分配 Python 副本前预留；同一 key 更新计量，不重复累计。"""
        with self._lock:
            if self._closed or not owner or size < 0 or size and self.require_registered_owner and owner not in self._owners:
                raise PreviewMemoryError("preview_memory_unavailable")
            previous = self._reservations.get((owner, key), 0)
            self._check_capacity(owner, size - previous)
            if size:
                self._reservations[owner, key] = size
            else:
                self._reservations.pop((owner, key), None)

    def release_reservations(self, owner: str, prefix: str) -> None:
        """Worker 确认退出后回收该运行的所有副本预算。"""
        with self._lock:
            for key in list(self._reservations):
                if key[0] == owner and key[1].startswith(prefix):
                    del self._reservations[key]

    def _get(self, owner: str, block_id: str) -> _Block:
        """不泄漏其他会话中是否存在同名对象。"""
        block = self._blocks.get(block_id)
        if block is None or block.owner != owner or block.retiring:
            raise PreviewMemoryError("preview_memory_unavailable")
        return block

    def write_chunk(self, owner: str, block_id: str, index: int, content: bytes | memoryview) -> None:
        """顺序写入上传块；拒绝重复、越界和 commit 后写入。"""
        with self._lock:
            block = self._get(owner, block_id)
            if block.ready or index != block.next_index or not 0 < len(content) <= PREVIEW_CHUNK_SIZE:
                raise PreviewMemoryError("preview_input_chunk_invalid")
            if block.written + len(content) > block.size:
                raise PreviewMemoryError("preview_input_length_invalid")
            block.memory.buf[block.written:block.written + len(content)] = content
            block.written += len(content)
            block.next_index += 1
            block.touched = monotonic()

    def commit(self, owner: str, block_id: str) -> dict:
        """完整校验后才暴露为输入；失败时由会话取消上传并释放。"""
        with self._lock:
            block = self._get(owner, block_id)
            if block.written != block.size:
                raise PreviewMemoryError("preview_input_incomplete")
            if block.digest and hashlib.sha256(block.memory.buf[:block.size]).hexdigest() != block.digest:
                raise PreviewMemoryError("preview_input_digest_invalid")
            block.ready = True
            block.touched = monotonic()
            return {"blob_id": block_id, "byte_length": block.size, "media_type": block.media_type}

    @contextmanager
    def borrow(self, owner: str, block_id: str) -> Iterator[memoryview]:
        """单进程只读借用；先释放 view 再归还 pin，避免 BufferError 或悬空指针。"""
        with self._lock:
            block = self._get(owner, block_id)
            if not block.ready:
                raise PreviewMemoryError("preview_input_incomplete")
            block.pins += 1
            view = block.memory.buf[:block.size].toreadonly()
        try:
            yield view
        finally:
            view.release()
            with self._lock:
                block.pins -= 1
                if block.retiring and not block.pins:
                    self._destroy(block_id, block)

    def pin_descriptor(self, owner: str, block_id: str) -> dict:
        """仅向受管 Worker 返回 SHM 描述；调用方必须在 Worker 退出/归还后 unpin。"""
        with self._lock:
            block = self._get(owner, block_id)
            if not block.ready:
                raise PreviewMemoryError("preview_input_incomplete")
            block.pins += 1
            return {"name": block.memory.name, "byte_length": block.size,
                    "blob_id": block_id, "media_type": block.media_type, "file_name": block.file_name}

    def unpin(self, owner: str, block_id: str) -> None:
        """归还跨进程借用；释放请求不影响仍在读的进程。"""
        with self._lock:
            block = self._blocks.get(block_id)
            if block is None or block.owner != owner or block.pins <= 0:
                raise PreviewMemoryError("preview_memory_pin_invalid")
            block.pins -= 1
            if block.retiring and not block.pins:
                self._destroy(block_id, block)

    def writer_descriptor(self, owner: str, block_id: str) -> dict:
        """只给受管 Worker 分配一次写借用，未发布内存对浏览器不可见。"""
        with self._lock:
            block = self._get(owner, block_id)
            if block.ready or block.pins or block.written:
                raise PreviewMemoryError("preview_writer_invalid")
            block.pins += 1
            block.upload = False
            return {"name": block.memory.name, "byte_length": block.size,
                    "blob_id": block_id, "media_type": block.media_type}

    def publish_writer(self, owner: str, block_id: str) -> dict:
        """Worker 关闭写映射之后确认完成；父进程收到确认才发布。"""
        with self._lock:
            block = self._get(owner, block_id)
            if block.ready or block.pins != 1:
                raise PreviewMemoryError("preview_writer_invalid")
            block.written = block.size
            result = self.commit(owner, block_id)
            self.unpin(owner, block_id)
            return result

    def release(self, owner: str, block_id: str) -> None:
        """撤销新借用权限，等最后借用者归还后释放。"""
        with self._lock:
            block = self._blocks.get(block_id)
            if block is None or block.owner != owner:
                return
            block.retiring = True
            if not block.pins:
                self._destroy(block_id, block)

    def release_owner(self, owner: str) -> None:
        """幂等释放会话资源，保留仍在执行的进程借用。"""
        with self._lock:
            self._owners.discard(owner)
            for block_id, block in list(self._blocks.items()):
                if block.owner == owner:
                    self.release(owner, block_id)

    def expire_uploads(self, *, now: float | None = None, idle_seconds: float = 60) -> None:
        """回收未使用的上传；提交失败的完整输入也过期，执行借用和显示不受影响。"""
        with self._lock:
            tick = monotonic() if now is None else now
            for block_id, block in list(self._blocks.items()):
                if not block.pins and (block.upload or not block.ready) and tick - block.touched >= idle_seconds:
                    self.release(block.owner, block_id)

    def _destroy(self, block_id: str, block: _Block) -> None:
        """唯一所有者负责 close/unlink，成功后才移除容量计量。"""
        block.memory.close()
        block.memory.unlink()
        del self._blocks[block_id]

    def stats(self) -> dict[str, int]:
        """返回验收需要的有界资源计数，不暴露内容或 SHM 名称。"""
        with self._lock:
            return {"blocks": len(self._blocks), "bytes": sum(b.size for b in self._blocks.values()),
                    "pins": sum(b.pins for b in self._blocks.values()),
                    "reserved_bytes": sum(self._reservations.values())}

    def live_ids(self, owner: str) -> set[str]:
        """监督器只保留仍然存在的发布块身份，长循环不累计释放历史。"""
        with self._lock:
            return {identity for identity, block in self._blocks.items() if block.owner == owner}

    def close(self) -> None:
        """停止新分配并撤销所有 owner；活跃进程必须先停止再完成释放。"""
        with self._lock:
            self._closed = True
            self._reservations.clear()
            for block_id, block in list(self._blocks.items()):
                self.release(block.owner, block_id)
