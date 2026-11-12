"""Preview Worker 的专用内存交接，控制队列不承载大图字节。"""

from multiprocessing.shared_memory import SharedMemory
from queue import Empty, Full
from threading import Lock, RLock
from uuid import uuid4


class PreviewMemoryBridge:
    """串行 RPC 确认分配和发布；共享段仅由父进程拥有与回收。"""

    def __init__(self, responses, replies):
        """responses 是 Worker 到父进程控制队列，replies 只用于内存 RPC。"""
        self.responses = responses
        self.replies = replies
        self.lock = Lock()
        self.budget_lock = RLock()
        self.reservations = {}
        self.credit = 0
        self.failed = False

    def call(self, action, **payload):
        """固定类型小消息；通道异常立即报告，不写磁盘或重试副作用。"""
        with self.lock:
            if self.failed:
                raise RuntimeError("preview_memory_channel_failed")
            request_id = uuid4().hex
            try:
                self.responses.put(("memory", {"request_id": request_id, "action": action, **payload}), timeout=2)
                response = self.replies.get(timeout=15)
            except (Empty, Full, EOFError, OSError) as error:
                # 超时后的迟到回复不能用于下一次 RPC；整条通道退出，不重试业务。
                self.failed = True
                raise RuntimeError(f"preview_memory_channel_failed:{action}") from error
            if response.get("request_id") != request_id:
                self.failed = True
                raise RuntimeError("preview_memory_protocol_invalid")
            if response.get("error"):
                raise ValueError(response["error"])
            return response["result"]

    def publish(self, content, media_type):
        """复制编码结果到受管 SHM，关闭写映射后发布为不可变 blob。"""
        descriptor = self.call("allocate", byte_length=len(content), media_type=media_type)
        memory = SharedMemory(name=descriptor["name"])
        try:
            memory.buf[:len(content)] = content
        finally:
            memory.close()
        return self.call("publish", blob_id=descriptor["blob_id"])

    def reserve(self, key, size):
        """按 MiB 申请额度，内部原子计量，避免小值逐项往返父进程。"""
        with self.budget_lock:
            needed = sum(self.reservations.values()) - self.reservations.get(key, 0) + size
            if size < 0:
                raise ValueError("preview_memory_capacity")
            credit = ((needed + 1024**2 - 1) // 1024**2) * 1024**2
            if needed > self.credit or self.credit - credit >= 8 * 1024**2:
                self.call("reserve", key="workspace", byte_length=credit)
                self.credit = credit
            if size:
                self.reservations[key] = size
            else:
                self.reservations.pop(key, None)

    def release(self, blob_id):
        """未交付给显示状态的编码结果可以立即回收。"""
        self.call("release", blob_id=blob_id)
