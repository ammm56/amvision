"""统一任务系统的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.service.infrastructure.persistence.base import Base


class ResourceProfileEntity(Base):
    """映射 ResourceProfile 对象。"""

    __tablename__ = "resource_profiles"

    resource_profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(128), index=True)
    worker_pool: Mapped[str] = mapped_column(String(128), index=True)
    executor_mode: Mapped[str] = mapped_column(String(64), default="process")
    max_concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    tasks: Mapped[list[TaskRecordEntity]] = relationship(
        back_populates="resource_profile",
        order_by="TaskRecordEntity.task_id",
    )


class TaskRecordEntity(Base):
    """映射 TaskRecord 对象。"""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_kind: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    task_spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    worker_pool: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    resource_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("resource_profiles.resource_profile_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(32), index=True)
    current_attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    resource_profile: Mapped[ResourceProfileEntity | None] = relationship(back_populates="tasks")
    attempts: Mapped[list[TaskAttemptEntity]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskAttemptEntity.attempt_no",
    )
    events: Mapped[list[TaskEventEntity]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskEventEntity.created_at",
    )


class TaskAttemptEntity(Base):
    """映射 TaskAttempt 对象。"""

    __tablename__ = "task_attempts"

    attempt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    host_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ended_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    task: Mapped[TaskRecordEntity] = relationship(back_populates="attempts")
    events: Mapped[list[TaskEventEntity]] = relationship(
        back_populates="attempt",
        order_by="TaskEventEntity.created_at",
    )


class TaskEventEntity(Base):
    """映射 TaskEvent 对象。"""

    __tablename__ = "task_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        index=True,
    )
    attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_attempts.attempt_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(String(1024), default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    task: Mapped[TaskRecordEntity] = relationship(back_populates="events")
    attempt: Mapped[TaskAttemptEntity | None] = relationship(back_populates="events")