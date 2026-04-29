"""Model 聚合的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.service.infrastructure.persistence.base import Base


class ModelRecord(Base):
    """映射 Model 聚合根。"""

    __tablename__ = "models"

    model_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_name: Mapped[str] = mapped_column(String(128), index=True)
    model_type: Mapped[str] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(64))
    model_scale: Mapped[str] = mapped_column(String(64))
    labels_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    versions: Mapped[list[ModelVersionRecord]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
        order_by="ModelVersionRecord.model_version_id",
    )
    builds: Mapped[list[ModelBuildRecord]] = relationship(
        back_populates="model",
        cascade="all, delete-orphan",
        order_by="ModelBuildRecord.model_build_id",
    )


class ModelVersionRecord(Base):
    """映射 ModelVersion 对象。"""

    __tablename__ = "model_versions"

    model_version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        ForeignKey("models.model_id", ondelete="CASCADE"),
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(64))
    dataset_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    training_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    model: Mapped[ModelRecord] = relationship(back_populates="versions")


class ModelBuildRecord(Base):
    """映射 ModelBuild 对象。"""

    __tablename__ = "model_builds"

    model_build_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        ForeignKey("models.model_id", ondelete="CASCADE"),
        index=True,
    )
    source_model_version_id: Mapped[str] = mapped_column(String(128), index=True)
    build_format: Mapped[str] = mapped_column(String(128))
    runtime_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    conversion_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    model: Mapped[ModelRecord] = relationship(back_populates="builds")