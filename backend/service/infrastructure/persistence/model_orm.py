"""Model 聚合的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.service.infrastructure.persistence.base import Base


class ModelRecord(Base):
    """映射 Model 聚合根。"""

    __tablename__ = "models"
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NULL AND owner_key = '__platform__') OR "
            "(project_id IS NOT NULL AND owner_key = project_id)",
            name="ck_models_owner_key_matches_project",
        ),
        UniqueConstraint(
            "scope_kind",
            "owner_key",
            "model_name",
            "task_type",
            "model_scale",
            name="uq_models_owner_name_task_scale",
        ),
        Index(
            "ix_models_catalog_lookup",
            "scope_kind",
            "owner_key",
            "task_type",
            "model_name",
            "model_scale",
        ),
    )

    model_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    owner_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
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
    __table_args__ = (
        Index("ix_model_versions_training_task_id", "training_task_id"),
        Index("ix_model_versions_parent_version_id", "parent_version_id"),
        Index("ix_model_versions_model_source", "model_id", "source_kind"),
    )

    model_version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        ForeignKey("models.model_id", ondelete="CASCADE"),
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(64))
    dataset_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    training_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="SET NULL"),
        nullable=True,
    )
    file_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    model: Mapped[ModelRecord] = relationship(back_populates="versions")
    parent_version: Mapped[ModelVersionRecord | None] = relationship(
        foreign_keys=[parent_version_id],
        remote_side=[model_version_id],
    )


class ModelBuildRecord(Base):
    """映射 ModelBuild 对象。"""

    __tablename__ = "model_builds"
    __table_args__ = (
        UniqueConstraint(
            "conversion_task_id",
            "build_format",
            "runtime_backend",
            "runtime_precision",
            name="uq_model_builds_conversion_target",
        ),
        Index("ix_model_builds_conversion_task_id", "conversion_task_id"),
        Index(
            "ix_model_builds_source_runtime",
            "source_model_version_id",
            "runtime_backend",
            "runtime_precision",
        ),
    )

    model_build_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        ForeignKey("models.model_id", ondelete="CASCADE"),
        index=True,
    )
    source_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="CASCADE"),
        index=True,
    )
    build_format: Mapped[str] = mapped_column(String(128))
    runtime_backend: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_precision: Mapped[str] = mapped_column(String(32), nullable=False)
    runtime_profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    conversion_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    model: Mapped[ModelRecord] = relationship(back_populates="builds")
    source_model_version: Mapped[ModelVersionRecord] = relationship(
        foreign_keys=[source_model_version_id]
    )
