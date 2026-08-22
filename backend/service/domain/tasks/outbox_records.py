"""任务队列 Transactional Outbox 领域记录。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


QueueOutboxState = Literal["pending", "leased", "dispatched"]


@dataclass(frozen=True)
class QueueOutboxMessage:
    """描述一条与业务事务共同提交的队列投递记录。"""

    message_id: str
    queue_name: str
    payload: dict[str, object]
    payload_fingerprint: str
    created_at: str
    available_at: str
    metadata: dict[str, object] = field(default_factory=dict)
    state: QueueOutboxState = "pending"
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    dispatched_at: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
