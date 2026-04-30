"""ModelFile 的 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class ModelFileRecord(Base):
    """映射 ModelFile 对象。"""

    __tablename__ = "model_files"

    file_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), index=True)
    file_type: Mapped[str] = mapped_column(String(128))
    logical_name: Mapped[str] = mapped_column(String(512))
    storage_uri: Mapped[str] = mapped_column(String(1024))
    model_version_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    model_build_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)