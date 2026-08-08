"""Project summary 的 SQLAlchemy 聚合读仓储。"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.projects.project_summary import ProjectDatabaseSummary
from backend.service.infrastructure.persistence.dataset_export_orm import (
    DatasetExportRecord,
)
from backend.service.infrastructure.persistence.dataset_import_orm import (
    DatasetImportRecord,
)
from backend.service.infrastructure.persistence.deployment_orm import (
    DeploymentInstanceRecord,
)
from backend.service.infrastructure.persistence.task_orm import TaskRecordEntity
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowAppRuntimeRecord,
    WorkflowPreviewRunRecord,
    WorkflowRunRecord,
)


class SqlAlchemyProjectSummaryRepository:
    """仅选择分组字段和 count，避免加载资源 JSON 与 ORM 实体。"""

    def __init__(self, session: Session) -> None:
        """保存当前只读查询使用的 SQLAlchemy Session。"""

        self.session = session

    def get_database_summary(self, project_id: str) -> ProjectDatabaseSummary:
        """通过数据库 group by 返回一个 Project 的所有状态计数。"""

        try:
            import_counts = self._count_by_one_column(
                DatasetImportRecord.status,
                DatasetImportRecord.project_id == project_id,
            )
            export_counts = self._count_by_one_column(
                DatasetExportRecord.status,
                DatasetExportRecord.project_id == project_id,
            )
            task_counts = self._count_tasks(project_id)
            preview_counts = self._count_by_one_column(
                WorkflowPreviewRunRecord.state,
                WorkflowPreviewRunRecord.project_id == project_id,
            )
            workflow_run_counts = self._count_by_one_column(
                WorkflowRunRecord.state,
                WorkflowRunRecord.project_id == project_id,
            )
            app_runtime_counts = self._count_by_one_column(
                WorkflowAppRuntimeRecord.observed_state,
                WorkflowAppRuntimeRecord.project_id == project_id,
            )
            deployment_counts = self._count_by_one_column(
                DeploymentInstanceRecord.status,
                DeploymentInstanceRecord.project_id == project_id,
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 Project summary 聚合计数失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return ProjectDatabaseSummary(
            import_status_counts=import_counts,
            export_status_counts=export_counts,
            task_state_counts_by_kind=task_counts,
            preview_run_state_counts=preview_counts,
            workflow_run_state_counts=workflow_run_counts,
            app_runtime_observed_state_counts=app_runtime_counts,
            deployment_status_counts=deployment_counts,
        )

    def _count_by_one_column(
        self,
        column: object,
        predicate: object,
    ) -> dict[str, int]:
        """按一个字符串字段分组并返回稳定排序的数量字典。"""

        rows = self.session.execute(
            select(column, func.count()).where(predicate).group_by(column)
        ).all()
        return _normalize_grouped_rows(rows)

    def _count_tasks(self, project_id: str) -> dict[str, dict[str, int]]:
        """按 task_kind 和 state 两级分组任务数量。"""

        rows = self.session.execute(
            select(
                TaskRecordEntity.task_kind,
                TaskRecordEntity.state,
                func.count(),
            )
            .where(TaskRecordEntity.project_id == project_id)
            .group_by(TaskRecordEntity.task_kind, TaskRecordEntity.state)
        ).all()
        grouped: dict[str, dict[str, int]] = {}
        for raw_kind, raw_state, raw_count in rows:
            if not isinstance(raw_kind, str) or not raw_kind.strip():
                continue
            if not isinstance(raw_state, str) or not raw_state.strip():
                continue
            grouped.setdefault(raw_kind.strip(), {})[raw_state.strip()] = int(raw_count)
        return {
            task_kind: {
                state: grouped[task_kind][state]
                for state in sorted(grouped[task_kind])
            }
            for task_kind in sorted(grouped)
        }


def _normalize_grouped_rows(rows: Iterable[tuple[object, object]]) -> dict[str, int]:
    """把数据库分组结果规范化为按 key 排序的正整数计数。"""

    counts = {
        raw_key.strip(): int(raw_count)
        for raw_key, raw_count in rows
        if isinstance(raw_key, str) and raw_key.strip()
    }
    return {key: counts[key] for key in sorted(counts)}
