"""Project 资源写操作与聚合删除之间的统一接纳边界。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from backend.service.application.errors import WorkflowRecoveryRequiredError
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_project_mutation_lifecycle_resource_key,
)
from backend.service.infrastructure.db.session import SessionFactory


class ProjectMutationAdmissionService:
    """复用持久 Project sentinel 接纳低频资源写操作。"""

    def __init__(self, session_factory: SessionFactory) -> None:
        """初始化 Project mutation 接纳服务。"""

        self.lifecycle = WorkflowApplicationLifecycleService(
            session_factory=session_factory,
            dataset_storage=None,
        )

    @contextmanager
    def operation(
        self,
        *,
        project_id: str,
        mutation_kind: str,
        resource_id: str,
    ) -> Iterator[None]:
        """占用单个资源 claim；冲突立即失败，资源处理期间不持 DB 事务。"""

        resource_key = build_project_mutation_lifecycle_resource_key(
            mutation_kind=mutation_kind,
            resource_id=resource_id,
        )
        claim = self.lifecycle.acquire(
            project_id=project_id,
            application_id=resource_key,
            operation="saving",
        )
        try:
            yield
        except WorkflowRecoveryRequiredError:
            raise
        except Exception:
            try:
                self.lifecycle.complete(claim, deleted=False)
                self.lifecycle.delete_idle_temporary_resource(claim)
            except Exception:  # noqa: BLE001 - 不覆盖原始业务异常
                pass
            raise
        self.lifecycle.complete(claim, deleted=False)
        try:
            self.lifecycle.delete_idle_temporary_resource(claim)
        except Exception:  # noqa: BLE001 - 资源已提交，Project 删除仍会清理 idle 行
            pass


__all__ = ["ProjectMutationAdmissionService"]
