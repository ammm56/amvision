"""Project 聚合删除的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.infrastructure.persistence.dataset_export_orm import (
    DatasetExportRecord,
)
from backend.service.infrastructure.persistence.dataset_import_orm import (
    DatasetImportRecord,
)
from backend.service.infrastructure.persistence.dataset_orm import DatasetVersionRecord
from backend.service.infrastructure.persistence.deployment_orm import (
    DeploymentInstanceRecord,
)
from backend.service.infrastructure.persistence.local_auth_orm import (
    LocalAuthUserRecord,
)
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from backend.service.infrastructure.persistence.model_orm import ModelRecord
from backend.service.infrastructure.persistence.task_orm import TaskRecordEntity
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowApplicationLifecycleRecord,
    WorkflowAppVersionRecord,
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

    def inspect(
        self,
        project_id: str,
        *,
        project_sentinel_resource_key: str | None = None,
    ) -> ProjectDatabaseInventory:
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
                    select(
                        WorkflowRunRecord.workflow_run_id, WorkflowRunRecord.state
                    ).where(WorkflowRunRecord.project_id == project_id)
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
                "workflow_app_versions": self._count(
                    WorkflowAppVersionRecord, project_id
                ),
                "workflow_runs": len(workflow_runs),
                "workflow_trigger_sources": len(trigger_sources),
                "workflow_execution_policies": self._count(
                    WorkflowExecutionPolicyRecord, project_id
                ),
                "workflow_application_lifecycles": self._count_lifecycles(
                    project_id,
                    excluded_application_id=project_sentinel_resource_key,
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

    def delete(
        self,
        project_id: str,
        *,
        project_sentinel_resource_key: str | None = None,
    ) -> None:
        """删除 Project 关联记录，由外层 Unit of Work 提交。"""

        try:
            # LocalAuthUserRecord 保存的是 Project id 数组，不是 Project 所有权记录。
            # 删除 Project 时必须同步撤销引用，避免将来复用同名 id 后旧权限复活。
            for user in self._auth_users_referencing(project_id):
                user.project_ids_json = [
                    value for value in user.project_ids_json if value != project_id
                ]
            # RuntimeRevision 同时引用 Runtime 和 AppVersion。先删除所有入口与
            # Runtime，并立即 flush 触发 revision 的数据库级 CASCADE，再删除
            # AppVersion，避免同一事务在不同数据库上因 flush 排序产生 FK 冲突。
            for model in (
                WorkflowTriggerSourceRecord,
                WorkflowRunRecord,
                WorkflowAppRuntimeRecord,
            ):
                self._delete_project_records(model, project_id)
            self.session.flush()

            self._delete_project_records(WorkflowAppVersionRecord, project_id)
            self.session.flush()

            self._delete_project_records(
                WorkflowApplicationLifecycleRecord,
                project_id,
                excluded_application_id=project_sentinel_resource_key,
            )
            self.session.flush()

            for model in (
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
                self._delete_project_records(model, project_id)
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
            self.session.execute(select(model).where(model.project_id == project_id))
            .scalars()
            .all()
        )

    def _count_lifecycles(
        self,
        project_id: str,
        *,
        excluded_application_id: str | None,
    ) -> int:
        """返回 Project lifecycle 数量，可排除持久删除 sentinel。"""

        statement = select(WorkflowApplicationLifecycleRecord).where(
            WorkflowApplicationLifecycleRecord.project_id == project_id
        )
        if excluded_application_id is not None:
            statement = statement.where(
                WorkflowApplicationLifecycleRecord.application_id
                != excluded_application_id
            )
        return len(self.session.execute(statement).scalars().all())

    def _delete_project_records(
        self,
        model: type[object],
        project_id: str,
        *,
        excluded_application_id: str | None = None,
    ) -> None:
        """将指定 Project 的某类 ORM 记录加入当前删除事务。"""

        statement = select(model).where(model.project_id == project_id)
        if (
            model is WorkflowApplicationLifecycleRecord
            and excluded_application_id is not None
        ):
            statement = statement.where(
                WorkflowApplicationLifecycleRecord.application_id
                != excluded_application_id
            )
        records = self.session.execute(statement).scalars().all()
        for record in records:
            self.session.delete(record)
