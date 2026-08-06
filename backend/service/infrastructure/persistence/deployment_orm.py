"""DeploymentInstance ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class DeploymentInstanceRecord(Base):
    """映射 DeploymentInstance 对象。"""

    __tablename__ = "deployment_instances"

    deployment_instance_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    model_version_id: Mapped[str] = mapped_column(String(128), index=True)
    model_build_id: Mapped[str | None] = mapped_column(
        String(128), index=True, nullable=True
    )
    runtime_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_backend: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str] = mapped_column(String(64))
    runtime_configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DeploymentRuntimeStateRecord(Base):
    """映射每个 DeploymentInstance 的 sync/async 持久化运行状态。"""

    __tablename__ = "deployment_runtime_states"
    __table_args__ = (
        UniqueConstraint(
            "deployment_instance_id",
            "runtime_mode",
            name="uq_deployment_runtime_state_instance_mode",
        ),
    )

    deployment_instance_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("deployment_instances.deployment_instance_id", ondelete="CASCADE"),
        primary_key=True,
    )
    runtime_mode: Mapped[str] = mapped_column(String(16), primary_key=True)
    desired_state: Mapped[str] = mapped_column(String(16), index=True)
    observed_state: Mapped[str] = mapped_column(String(32), index=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    controller_owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    controller_lease_expires_at: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    next_restart_at: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    last_started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_stopped_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)
