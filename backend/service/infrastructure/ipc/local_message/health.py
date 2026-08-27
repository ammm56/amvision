"""LocalMessage 不同 Channel 类型的分离 health 快照。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MailboxChannelHealth:
    """Mailbox descriptor/page 与生命周期计数。"""

    channel_id: UUID
    owner_epoch: int
    closed: bool
    free_descriptors: int
    request_descriptors: int
    processing_descriptors: int
    response_descriptors: int
    free_pages: int
    requests_total: int
    responses_total: int
    acknowledgements_total: int
    cancellations_total: int
    deadline_exceeded_total: int
    capacity_rejections_total: int


@dataclass(frozen=True, slots=True)
class EventChannelHealth:
    """EventRing producer、sequence、gap 和 drop 计数。"""

    channel_id: UUID
    owner_epoch: int
    session_id: UUID
    closed: bool
    published_sequence: int
    dropped_total: int
    reader_gap_total: int


@dataclass(frozen=True, slots=True)
class LocalMessageChannelHealthEnvelope:
    """只统一 identity/transport，类型专属指标保持互斥。"""

    channel_name: str
    channel_kind: Literal["mailbox", "event"]
    transport: Literal["mmap"]
    profile_id: str
    mailbox: MailboxChannelHealth | None = None
    event: EventChannelHealth | None = None

    def __post_init__(self) -> None:
        """要求 envelope 只携带对应类型的一组指标。"""

        if self.channel_kind == "mailbox" and (self.mailbox is None or self.event is not None):
            raise ValueError("Mailbox health envelope 类型不一致")
        if self.channel_kind == "event" and (self.event is None or self.mailbox is not None):
            raise ValueError("Event health envelope 类型不一致")
