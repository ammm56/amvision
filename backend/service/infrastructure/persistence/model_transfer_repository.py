"""模型传递操作与导入产物归属仓储，使用调用方的事务。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, ForeignKey, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


def transfer_now() -> str:
    """返回可排序的 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat()


class ImportedModelArtifactRecord(Base):
    """仅服务可登记的版本或 Build 文件所有权。"""

    __tablename__ = "imported_model_artifacts"
    __table_args__ = (CheckConstraint("(model_version_id IS NOT NULL AND model_build_id IS NULL) OR (model_version_id IS NULL AND model_build_id IS NOT NULL)", name="ck_imported_model_artifact_one_owner"),)
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.model_version_id", ondelete="CASCADE"), nullable=True, unique=True)
    model_build_id: Mapped[str | None] = mapped_column(ForeignKey("model_builds.model_build_id", ondelete="CASCADE"), nullable=True, unique=True)
    object_prefix: Mapped[str] = mapped_column(String(1024))
    fingerprint: Mapped[str] = mapped_column(String(64))
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ModelTransferRecord(Base):
    """短期操作和崩溃恢复清单，永久模型不依赖此行存在。"""

    __tablename__ = "model_deployment_transfers"
    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class ModelTransferRepository:
    """封装操作查询与保存，事务由 UoW 提交。"""

    def __init__(self, session):
        self.session = session

    def get(self, operation_id: str) -> ModelTransferRecord | None:
        """读取单个操作。"""
        return self.session.get(ModelTransferRecord, operation_id)

    def list(self, project_id: str | None = None) -> list[ModelTransferRecord]:
        """按创建时间读取短期操作。"""
        statement = select(ModelTransferRecord).order_by(ModelTransferRecord.created_at)
        if project_id is not None:
            statement = statement.where(ModelTransferRecord.project_id == project_id)
        return list(self.session.scalars(statement))

    def save(self, *, operation_id: str, project_id: str, direction: str, state: str, payload: dict) -> None:
        """整体替换 JSON，确保 ORM 能追踪恢复记录变化。"""
        row = self.get(operation_id)
        if row is None:
            row = ModelTransferRecord(operation_id=operation_id, project_id=project_id, direction=direction, created_at=transfer_now())
            self.session.add(row)
        row.state, row.payload_json, row.updated_at = state, payload, transfer_now()
