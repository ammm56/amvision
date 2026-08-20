"""ModelFile 的 ORM 实体定义。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.service.infrastructure.persistence.base import Base

if TYPE_CHECKING:
    from backend.service.infrastructure.persistence.model_orm import ModelRecord


class ModelFileRecord(Base):
    """映射 ModelFile 对象。"""

    __tablename__ = "model_files"
    __table_args__ = (
        CheckConstraint(
            "model_version_id IS NULL OR model_build_id IS NULL",
            name="ck_model_files_single_artifact_owner",
        ),
        UniqueConstraint(
            "model_version_id",
            "file_type",
            "logical_name",
            name="uq_model_files_version_logical_name",
        ),
        UniqueConstraint(
            "model_build_id",
            "file_type",
            "logical_name",
            name="uq_model_files_build_logical_name",
        ),
        Index("ix_model_files_model_type", "model_id", "file_type"),
    )

    file_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(
        ForeignKey("models.model_id", ondelete="CASCADE"),
        index=True,
    )
    file_type: Mapped[str] = mapped_column(String(128))
    logical_name: Mapped[str] = mapped_column(String(512))
    storage_uri: Mapped[str] = mapped_column(String(1024))
    model_version_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    model_build_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    model: Mapped[ModelRecord] = relationship()
