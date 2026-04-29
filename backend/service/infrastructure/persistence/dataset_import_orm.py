"""DatasetImport 的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class DatasetImportRecord(Base):
    """映射 DatasetImport 对象。"""

    __tablename__ = "dataset_imports"

    dataset_import_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    format_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(64))
    dataset_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    package_path: Mapped[str] = mapped_column(String(1024))
    staging_path: Mapped[str] = mapped_column(String(1024))
    version_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_root: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    annotation_root: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    manifest_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    split_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    class_map_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    detected_profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)