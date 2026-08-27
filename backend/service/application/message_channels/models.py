"""LocalMessage 四个窄 port 共用的不可变 DTO。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class EventPublishResult(StrEnum):
    """Event publisher 的非阻塞结果。"""

    PUBLISHED = "published"
    FULL = "full"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class RpcRequestContext:
    """Server 已 claim 的请求及其协作式取消观察器。"""

    request_id: UUID
    wire_bytes: bytes
    deadline_ns: int
    owner_epoch: int
    _cancel_probe: Callable[[], bool] = field(repr=False, compare=False)
    _transport_token: object = field(repr=False, compare=False)

    @property
    def cancelled(self) -> bool:
        """返回 client 取消、deadline 到期或 owner fence 的当前状态。"""

        return bool(self._cancel_probe())


@dataclass(frozen=True, slots=True)
class EventCursor:
    """绑定 producer epoch/session 的 EventRing 读取位置。"""

    owner_epoch: int
    session_id: UUID
    sequence: int

    def __post_init__(self) -> None:
        """拒绝无法表示的 cursor。"""

        if self.owner_epoch <= 0:
            raise ValueError("Event cursor owner_epoch 必须大于 0")
        if self.sequence < 0:
            raise ValueError("Event cursor sequence 不能小于 0")


@dataclass(frozen=True, slots=True)
class EventBatch:
    """一次 EventRing 读取的不可变结果。"""

    events: tuple[bytes, ...]
    next_cursor: EventCursor
    gap_detected: bool
    producer_closed: bool
