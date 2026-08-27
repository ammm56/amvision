"""结构化消息通道的协议中立应用层 ports。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.service.application.message_channels.models import (
    EventBatch,
    EventCursor,
    EventPublishResult,
    RpcRequestContext,
)


class CancellationSource(Protocol):
    """调用方提供的非阻塞取消观察器。"""

    def is_cancelled(self) -> bool:
        """返回请求是否已经取消。"""


class RpcResponseHandle(Protocol):
    """持有 response bytes 与 ACK 生命周期。"""

    @property
    def wire_bytes(self) -> bytes:
        """返回 client 已复制到自身所有权的不可变响应。"""

    def ack(self) -> None:
        """幂等确认响应已经完成消费。"""

    def close(self) -> None:
        """幂等结束 handle；普通响应等价于 ACK。"""


class RpcClientPort(Protocol):
    """同步、有 deadline 的本机 RPC client。"""

    def call(
        self,
        *,
        request_id: UUID,
        wire_bytes: bytes,
        deadline_ns: int,
        cancellation: CancellationSource | None = None,
    ) -> RpcResponseHandle:
        """提交一次调用并返回受控 response handle。"""

    def close(self, *, deadline_ns: int) -> None:
        """幂等关闭 client endpoint。"""


class RpcServerPort(Protocol):
    """单 owner RPC server。"""

    def receive(self, *, deadline_ns: int) -> RpcRequestContext | None:
        """在 deadline 前返回一个请求；无请求时返回 None。"""

    def publish_response(
        self,
        request: RpcRequestContext,
        *,
        wire_bytes: bytes,
    ) -> None:
        """为请求最多发布一次响应。"""

    def close(self, *, deadline_ns: int) -> None:
        """停止接收新请求并有界关闭 owner。"""


class EventPublisherPort(Protocol):
    """单 producer、非阻塞 Event publisher。"""

    def try_publish(self, wire_bytes: bytes) -> EventPublishResult:
        """发布事件或返回固定容量/关闭结果。"""

    def close(self, *, deadline_ns: int) -> None:
        """发布 graceful close 并关闭 owner。"""


class EventReaderPort(Protocol):
    """按 cursor 读取 EventRing。"""

    def read(
        self,
        *,
        cursor: EventCursor | None,
        deadline_ns: int,
        limit: int,
    ) -> EventBatch:
        """读取事件、gap 和 producer close 状态。"""

    def close(self, *, deadline_ns: int) -> None:
        """幂等关闭 reader endpoint。"""
