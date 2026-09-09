"""HTTP 实例身份与就绪状态，不访问业务依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from threading import Condition
from uuid import uuid4


@dataclass
class ServiceLiveness:
    """每个应用实例独立的启动身份与生命周期阶段。"""

    instance_id: str = field(default_factory=lambda: uuid4().hex)
    pid: int = field(default_factory=os.getpid)
    phase: str = "starting"
    active_requests: int = 0
    _requests: Condition = field(default_factory=Condition, repr=False)

    def begin_request(self) -> bool:
        """HTTP 接入与排空原子交接，不影响 ZeroMQ 或共享内存热路径。"""
        with self._requests:
            if self.phase in {"draining", "stopped"}:
                return False
            self.active_requests += 1
            return True

    def end_request(self) -> None:
        """完整 ASGI 响应结束后释放 HTTP 在途计数。"""
        with self._requests:
            self.active_requests -= 1
            if not self.active_requests:
                self._requests.notify_all()

    def begin_drain(self, *, timeout: float = 30) -> None:
        """关闭新 HTTP 接入，等待已经接受的响应或流释放。"""
        with self._requests:
            self.phase = "draining"
            if not self._requests.wait_for(lambda: self.active_requests == 0, timeout=timeout):
                raise TimeoutError("HTTP 请求或响应流尚未排空，禁止自动重启")

    def snapshot(self) -> dict[str, str | int]:
        """生成固定大小的公开 liveness 响应。"""
        return {
            "format_id": "amvision.service-liveness.v1",
            "instance_id": self.instance_id,
            "pid": self.pid,
            "phase": self.phase,
        }
