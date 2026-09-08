"""Runtime 与 Trigger 物理删除暂存的启动恢复。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from backend.service.application.workflows.resource_deletion_staging import (
    finalize_staged_workflow_resource_storage,
    list_staged_workflow_resource_storage,
    restore_staged_workflow_resource_storage,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class WorkflowResourceDeletionRecoveryResult:
    """描述启动期 Runtime/Trigger 删除暂存恢复结果。"""

    restored_deletions: int
    completed_cleanups: int


class WorkflowResourceDeletionRecoveryService:
    """按数据库记录是否存在恢复或完成资源物理删除。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> None:
        """初始化恢复服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage

    def recover(self) -> WorkflowResourceDeletionRecoveryResult:
        """恢复未提交删除并清理已提交删除，不启动后台任务。"""

        restored = 0
        completed = 0
        for resource_kind in ("workflow-runtime", "workflow-trigger"):
            for staging in list_staged_workflow_resource_storage(
                dataset_storage=self.dataset_storage,
                resource_kind=resource_kind,
            ):
                with self._open_unit_of_work() as unit_of_work:
                    if resource_kind == "workflow-runtime":
                        record_exists = (
                            unit_of_work.workflow_runtime.get_workflow_app_runtime(
                                staging.resource_id
                            )
                            is not None
                        )
                    else:
                        record_exists = (
                            unit_of_work.workflow_trigger_sources.get_trigger_source(
                                staging.resource_id
                            )
                            is not None
                        )
                if record_exists:
                    restore_staged_workflow_resource_storage(
                        dataset_storage=self.dataset_storage,
                        staging=staging,
                    )
                    restored += 1
                else:
                    pending = finalize_staged_workflow_resource_storage(
                        dataset_storage=self.dataset_storage,
                        staging=staging,
                    )
                    if pending is None:
                        completed += 1
        return WorkflowResourceDeletionRecoveryResult(
            restored_deletions=restored,
            completed_cleanups=completed,
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并关闭一个只读 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        finally:
            unit_of_work.close()
