"""Preview Worker 的专用内存交接，控制队列不承载大图字节。"""

from multiprocessing.shared_memory import SharedMemory
from threading import Lock
from uuid import uuid4


class PreviewMemoryBridge:
    """串行 RPC 确认分配和发布；共享段仅由父进程拥有与回收。"""

    def __init__(self, responses, replies):
        """responses 是 Worker 到父进程控制队列，replies 只用于内存 RPC。"""
        self.responses = responses
        self.replies = replies
        self.lock = Lock()

    def call(self, action, **payload):
        """固定类型小消息；通道异常立即报告，不写磁盘或重试副作用。"""
        with self.lock:
            request_id = uuid4().hex
            self.responses.put(("memory", {"request_id": request_id, "action": action, **payload}), timeout=2)
            response = self.replies.get(timeout=15)
            if response.get("request_id") != request_id:
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
        """矩阵复制与编码工作区在父进程统一预算中预留。"""
        self.call("reserve", key=key, byte_length=size)

    def release(self, blob_id):
        """未交付给显示状态的编码结果可以立即回收。"""
        self.call("release", blob_id=blob_id)
