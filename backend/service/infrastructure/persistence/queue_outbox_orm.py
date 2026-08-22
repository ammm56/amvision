"""任务队列 Transactional Outbox ORM 实体。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class QueueOutboxMessageEntity(Base):
    """映射一条待投递或已投递的稳定队列消息。"""

    __tablename__ = "queue_outbox_messages"
    __table_args__ = (
        Index(
            "ix_queue_outbox_dispatch_scan",
            "state",
            "available_at",
            "lease_expires_at",
            "created_at",
        ),
    )

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    queue_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    available_at: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatched_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
