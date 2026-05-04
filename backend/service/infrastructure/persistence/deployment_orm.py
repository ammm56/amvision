"""DeploymentInstance ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class DeploymentInstanceRecord(Base):
    """映射 DeploymentInstance 对象。"""

    __tablename__ = "deployment_instances"

    deployment_instance_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    model_version_id: Mapped[str] = mapped_column(String(128), index=True)
    model_build_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    runtime_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_backend: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)