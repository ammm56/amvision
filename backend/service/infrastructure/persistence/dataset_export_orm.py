"""DatasetExport 的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class DatasetExportRecord(Base):
    """映射 DatasetExport 对象。"""

    __tablename__ = "dataset_exports"

    dataset_export_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    dataset_version_id: Mapped[str] = mapped_column(String(128), index=True)
    format_id: Mapped[str] = mapped_column(String(64))
    task_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    include_test_split: Mapped[bool] = mapped_column(Boolean, default=True)
    export_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    manifest_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    split_names_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    category_names_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)