"""Project 聚合删除的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.infrastructure.persistence.dataset_export_orm import DatasetExportRecord
from backend.service.infrastructure.persistence.dataset_import_orm import DatasetImportRecord
from backend.service.infrastructure.persistence.dataset_orm import DatasetVersionRecord
from backend.service.infrastructure.persistence.deployment_orm import DeploymentInstanceRecord
from backend.service.infrastructure.persistence.local_auth_orm import LocalAuthUserRecord
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from backend.service.infrastructure.persistence.model_orm import ModelRecord
from backend.service.infrastructure.persistence.task_orm import TaskRecordEntity
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowAppRuntimeRecord,
    WorkflowExecutionPolicyRecord,
    WorkflowPreviewRunRecord,
    WorkflowRunRecord,
)
from backend.service.infrastructure.persistence.workflow_trigger_source_orm import (
    WorkflowTriggerSourceRecord,
)


@dataclass(frozen=True)
class ProjectDatabaseInventory:
    """Project 删除所需的数据库资源快照。"""

    tasks: tuple[tuple[str, str], ...]
    deployments: tuple[tuple[str, str], ...]
    preview_runs: tuple[tuple[str, str], ...]
    app_runtimes: tuple[tuple[str, str, str], ...]
    workflow_runs: tuple[tuple[str, str], ...]
    trigger_sources: tuple[tuple[str, bool, str, str], ...]
    model_file_storage_uris: tuple[str, ...]
    counts: dict[str, int]


class SqlAlchemyProjectDeletionRepository:
    """在单个事务内盘点并删除 Project 关联记录。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def inspect(self, project_id: str) -> ProjectDatabaseInventory:
        """读取 Project 关联资源快照。"""

        try:
            tasks = tuple(
                self.session.execute(
                    select(TaskRecordEntity.task_id, TaskRecordEntity.state).where(
                        TaskRecordEntity.project_id == project_id
                    )
                ).all()
            )
            deployments = tuple(
                self.session.execute(
                    select(
                        DeploymentInstanceRecord.deployment_instance_id,
                        DeploymentInstanceRecord.status,
                    ).where(DeploymentInstanceRecord.project_id == project_id)
                ).all()
            )
            preview_runs = tuple(
                self.session.execute(
                    select(
                        WorkflowPreviewRunRecord.preview_run_id,
                        WorkflowPreviewRunRecord.state,
                    ).where(WorkflowPreviewRunRecord.project_id == project_id)
                ).all()
            )
            app_runtimes = tuple(
                self.session.execute(
                    select(
                        WorkflowAppRuntimeRecord.workflow_runtime_id,
                        WorkflowAppRuntimeRecord.desired_state,
                        WorkflowAppRuntimeRecord.observed_state,
                    ).where(WorkflowAppRuntimeRecord.project_id == project_id)
                ).all()
            )
            workflow_runs = tuple(
                self.session.execute(
                    select(WorkflowRunRecord.workflow_run_id, WorkflowRunRecord.state).where(
                        WorkflowRunRecord.project_id == project_id
                    )
                ).all()
            )
            trigger_sources = tuple(
                self.session.execute(
                    select(
                        WorkflowTriggerSourceRecord.trigger_source_id,
                        WorkflowTriggerSourceRecord.enabled,
                        WorkflowTriggerSourceRecord.desired_state,
                        WorkflowTriggerSourceRecord.observed_state,
                    ).where(WorkflowTriggerSourceRecord.project_id == project_id)
                ).all()
            )
            model_file_storage_uris = tuple(
                value
                for value in self.session.execute(
                    select(ModelFileRecord.storage_uri).where(
                        ModelFileRecord.project_id == project_id
                    )
                ).scalars()
                if value
            )
            counts = {
                "dataset_versions": self._count(DatasetVersionRecord, project_id),
                "dataset_imports": self._count(DatasetImportRecord, project_id),
                "dataset_exports": self._count(DatasetExportRecord, project_id),
                "tasks": len(tasks),
                "models": self._count(ModelRecord, project_id),
                "model_files": len(model_file_storage_uris),
                "deployments": len(deployments),
                "workflow_preview_runs": len(preview_runs),
                "workflow_app_runtimes": len(app_runtimes),
                "workflow_runs": len(workflow_runs),
                "workflow_trigger_sources": len(trigger_sources),
                "workflow_execution_policies": self._count(
                    WorkflowExecutionPolicyRecord, project_id
                ),
                "authorization_assignments": len(
                    self._auth_users_referencing(project_id)
                ),
            }
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 Project 删除快照失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return ProjectDatabaseInventory(
            tasks=tasks,
            deployments=deployments,
            preview_runs=preview_runs,
            app_runtimes=app_runtimes,
            workflow_runs=workflow_runs,
            trigger_sources=trigger_sources,
            model_file_storage_uris=model_file_storage_uris,
            counts=counts,
        )

    def delete(self, project_id: str) -> None:
        """删除 Project 关联记录，由外层 Unit of Work 提交。"""

        try:
            # LocalAuthUserRecord 保存的是 Project id 数组，不是 Project 所有权记录。
            # 删除 Project 时必须同步撤销引用，避免将来复用同名 id 后旧权限复活。
            for user in self._auth_users_referencing(project_id):
                user.project_ids_json = [
                    value for value in user.project_ids_json if value != project_id
                ]
            for model in (
                WorkflowTriggerSourceRecord,
                WorkflowRunRecord,
                WorkflowAppRuntimeRecord,
                WorkflowPreviewRunRecord,
                WorkflowExecutionPolicyRecord,
                DeploymentInstanceRecord,
                ModelFileRecord,
                ModelRecord,
                TaskRecordEntity,
                DatasetExportRecord,
                DatasetImportRecord,
                DatasetVersionRecord,
            ):
                records = self.session.execute(
                    select(model).where(model.project_id == project_id)
                ).scalars().all()
                for record in records:
                    self.session.delete(record)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "删除 Project 关联记录失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def _auth_users_referencing(self, project_id: str) -> list[LocalAuthUserRecord]:
        """返回授权列表中引用指定 Project 的本地用户。"""

        users = self.session.execute(select(LocalAuthUserRecord)).scalars().all()
        return [user for user in users if project_id in (user.project_ids_json or [])]

    def _count(self, model: type[object], project_id: str) -> int:
        """返回指定表中的 Project 记录数。"""

        return len(
            self.session.execute(
                select(model).where(model.project_id == project_id)
            ).scalars().all()
        )
