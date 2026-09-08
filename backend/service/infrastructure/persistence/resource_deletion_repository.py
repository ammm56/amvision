"""资源删除的 ORM 库存、事务及恢复清单仓储。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.service.domain.resource_deletion import (
    ResourceDeletionOperation,
    ResourceDeletionPlan,
    ResourceRef,
)
from backend.service.infrastructure.persistence.base import Base
from backend.service.infrastructure.persistence.dataset_orm import DatasetVersionRecord
from backend.service.infrastructure.persistence.dataset_import_orm import (
    DatasetImportRecord,
)
from backend.service.infrastructure.persistence.dataset_export_orm import (
    DatasetExportRecord,
)
from backend.service.infrastructure.persistence.model_orm import (
    ModelRecord,
    ModelVersionRecord,
    ModelBuildRecord,
)
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from backend.service.infrastructure.persistence.task_orm import (
    TaskRecordEntity,
    TaskAttemptEntity,
)
from backend.service.infrastructure.persistence.model_transfer_repository import (
    ImportedModelArtifactRecord,
)
from backend.service.infrastructure.persistence.queue_outbox_orm import (
    QueueOutboxMessageEntity,
)
from backend.service.infrastructure.persistence.deployment_orm import (
    DeploymentInstanceRecord,
    DeploymentRuntimeStateRecord,
)
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowAppVersionRecord,
    WorkflowAppRuntimeRecord,
)


class ResourceDeletionRecord(Base):
    """映射独立于业务 Task 的短期恢复清单。"""

    __tablename__ = "resource_deletions"
    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    plan_json: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


# 删除表由代码固定；调用方不能传入表名或任意 SQL。
RESOURCE_TABLES = {
    "imported-artifact": ImportedModelArtifactRecord,
    "task": TaskRecordEntity,
    "dataset-import": DatasetImportRecord,
    "dataset-export": DatasetExportRecord,
    "dataset-version": DatasetVersionRecord,
    "model-version": ModelVersionRecord,
    "model-build": ModelBuildRecord,
    "model-file": ModelFileRecord,
    "model": ModelRecord,
    "deployment": DeploymentInstanceRecord,
    "outbox": QueueOutboxMessageEntity,
}


class ResourceDeletionRepository:
    """读取聚合根库存并按固定顺序事务删除，不加载数据集样本。"""

    def __init__(self, session: Session) -> None:
        """使用调用方事务，所有提交由 UoW 决定。"""
        self.session = session

    def inventory(self) -> dict[str, list[dict]]:
        """返回跨项目引用检查需要的聚合根字段，不包含 ORM 对象。"""
        tables = {
            **RESOURCE_TABLES,
            "workflow-version": WorkflowAppVersionRecord,
            "workflow-runtime": WorkflowAppRuntimeRecord,
            "deployment-state": DeploymentRuntimeStateRecord,
            "task-attempt": TaskAttemptEntity,
        }
        return {
            kind: [
                {
                    column.name: deepcopy(getattr(row, column.name))
                    for column in table.__table__.columns
                }
                for row in self.session.scalars(select(table))
            ]
            for kind, table in tables.items()
        }

    def delete_records(self, references: list[ResourceRef]) -> None:
        """按外键顺序删除业务聚合和精确关联 Outbox。"""
        removed_files = {
            ref.resource_id for ref in references if ref.kind == "model-file"
        }
        if removed_files:
            for model in self.session.scalars(
                select(ModelRecord).where(ModelRecord.labels_file_id.in_(removed_files))
            ):
                # 版本保留各自的标签引用，聚合入口不能继续指向已删除文件。
                model.labels_file_id = None
        for kind in (
            "imported-artifact",
            "outbox",
            "deployment",
            "model-file",
            "model-build",
            "model-version",
            "model",
            "task",
            "dataset-export",
            "dataset-import",
            "dataset-version",
        ):
            for reference in references:
                if reference.kind != kind:
                    continue
                row = self.session.get(RESOURCE_TABLES[kind], reference.resource_id)
                if row is not None:
                    self.session.delete(row)
            self.session.flush()

    def save(self, operation: ResourceDeletionOperation) -> None:
        """保存可恢复状态，提交状态与业务删除使用同一事务。"""
        record = self.session.get(ResourceDeletionRecord, operation.plan.operation_id)
        if record is None:
            record = ResourceDeletionRecord(operation_id=operation.plan.operation_id)
            self.session.add(record)
        record.project_id = operation.plan.project_id
        record.state = operation.state
        record.plan_json = operation.plan.model_dump(mode="json")
        record.error = operation.error[:2048] if operation.error else None
        record.updated_at = datetime.now(timezone.utc).isoformat()

    def get(self, operation_id: str) -> ResourceDeletionOperation | None:
        """按操作 id 回读权威阶段，避免以资源是否存在猜测提交结果。"""
        row = self.session.get(ResourceDeletionRecord, operation_id)
        return None if row is None else self._domain(row)

    def list_pending(self) -> list[ResourceDeletionOperation]:
        """列出待恢复或待物理清理的操作。"""
        return [
            self._domain(row)
            for row in self.session.scalars(
                select(ResourceDeletionRecord).where(
                    ResourceDeletionRecord.state.in_(("prepared", "committed"))
                )
            )
        ]

    def prune_receipts(self) -> None:
        """异步完成回执最多保存一天或最近一千项，不长期保存产物清单。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rows = self.session.scalars(
            select(ResourceDeletionRecord)
            .where(ResourceDeletionRecord.state.in_(("completed", "rolled_back")))
            .order_by(ResourceDeletionRecord.updated_at.desc())
        )
        for index, row in enumerate(rows):
            if index >= 1000 or row.updated_at < cutoff:
                self.session.delete(row)

    def remove(self, operation_id: str) -> None:
        """全部清理完成后移除恢复记录。"""
        row = self.session.get(ResourceDeletionRecord, operation_id)
        if row is not None:
            self.session.delete(row)

    @staticmethod
    def _domain(row: ResourceDeletionRecord) -> ResourceDeletionOperation:
        """验证数据库清单格式后返回领域模型。"""
        return ResourceDeletionOperation(
            plan=ResourceDeletionPlan.model_validate(row.plan_json),
            state=row.state,
            error=row.error,
        )
