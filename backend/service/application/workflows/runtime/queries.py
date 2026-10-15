"""Workflow Runtime 的只读查询；不持有 worker、锁、缓存或状态转换职责。"""

from __future__ import annotations

from collections.abc import Callable
from typing import ContextManager

from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime, WorkflowRuntimeRevision, WorkflowExecutionPolicy, WorkflowRun,
)
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class WorkflowRuntimeQueries:
    """通过独立 Unit of Work 查询运行记录，维持原有项目可见性和 NotFound 语义。"""

    def __init__(self, open_unit_of_work: Callable[[], ContextManager[SqlAlchemyUnitOfWork]]) -> None:
        """open_unit_of_work 提供现有数据库事务边界。"""
        self._open_unit_of_work = open_unit_of_work

    def list_execution_policies(
        self, *, project_id: str
    ) -> tuple[WorkflowExecutionPolicy, ...]:
        """按 Project id 列出 WorkflowExecutionPolicy。"""

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError(
                "查询 WorkflowExecutionPolicy 列表时 project_id 不能为空"
            )
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_execution_policies(
                normalized_project_id
            )

    def get_execution_policy(self, execution_policy_id: str) -> WorkflowExecutionPolicy:
        """按 id 读取一条 WorkflowExecutionPolicy。"""

        with self._open_unit_of_work() as unit_of_work:
            execution_policy = unit_of_work.workflow_runtime.get_execution_policy(
                execution_policy_id
            )
        if execution_policy is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowExecutionPolicy 不存在",
                details={"execution_policy_id": execution_policy_id},
            )
        return execution_policy

    def list_workflow_app_runtimes(
        self,
        *,
        project_id: str,
        application_id: str | None = None,
        application_ids: tuple[str, ...] | None = None,
    ) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 和可选 Application 过滤条件列出 Runtime。"""

        normalized_project_id = project_id.strip()
        if not normalized_project_id:
            raise InvalidRequestError(
                "查询 WorkflowAppRuntime 列表时 project_id 不能为空"
            )
        normalized_application_id = (
            application_id.strip() if application_id is not None else None
        )
        if application_id is not None and not normalized_application_id:
            raise InvalidRequestError("application_id 不能为空字符串")
        if application_id is not None and application_ids is not None:
            raise InvalidRequestError("application_id 与 application_ids 不能同时使用")
        normalized_application_ids: tuple[str, ...] | None = None
        if application_ids is not None:
            normalized_application_ids = tuple(
                dict.fromkeys(item.strip() for item in application_ids if item.strip())
            )
            if not normalized_application_ids:
                raise InvalidRequestError("application_ids 至少需要一个有效 id")
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_workflow_app_runtimes(
                normalized_project_id,
                application_id=normalized_application_id,
                application_ids=normalized_application_ids,
            )

    def get_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """按 id 读取一个 WorkflowAppRuntime。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
        if workflow_app_runtime is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowAppRuntime 不存在",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        return workflow_app_runtime

    def get_visible_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> WorkflowAppRuntime:
        """按公开调用方的 Project 可见范围读取 WorkflowAppRuntime。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_visible_workflow_app_runtime(
                    workflow_runtime_id,
                    visible_project_ids=visible_project_ids,
                )
            )
        if workflow_app_runtime is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowAppRuntime 不存在",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        return workflow_app_runtime

    def list_workflow_runtime_revisions(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRuntimeRevision, ...]:
        """列出 Runtime 全部历史 revision。"""

        self.get_workflow_app_runtime(workflow_runtime_id)
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_workflow_runtime_revisions(
                workflow_runtime_id
            )

    def get_workflow_runtime_revision(
        self,
        workflow_runtime_id: str,
        workflow_runtime_revision_id: str,
    ) -> WorkflowRuntimeRevision:
        """读取属于指定稳定 Runtime 的一条 revision。"""

        self.get_workflow_app_runtime(workflow_runtime_id)
        with self._open_unit_of_work() as unit_of_work:
            revision = unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                workflow_runtime_revision_id
            )
        if revision is None or revision.workflow_runtime_id != workflow_runtime_id:
            raise ResourceNotFoundError(
                "请求的 WorkflowRuntimeRevision 不存在",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "workflow_runtime_revision_id": workflow_runtime_revision_id,
                },
            )
        return revision

    def get_visible_workflow_runtime_revision(
        self,
        workflow_runtime_id: str,
        workflow_runtime_revision_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> WorkflowRuntimeRevision:
        """按稳定 Runtime、revision id 和 Project 可见范围读取 revision。"""

        with self._open_unit_of_work() as unit_of_work:
            revision = (
                unit_of_work.workflow_runtime.get_visible_workflow_runtime_revision(
                    workflow_runtime_id,
                    workflow_runtime_revision_id,
                    visible_project_ids=visible_project_ids,
                )
            )
        if revision is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRuntimeRevision 不存在",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "workflow_runtime_revision_id": workflow_runtime_revision_id,
                },
            )
        return revision

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        """按 id 读取一个 WorkflowRun。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
        if workflow_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRun 不存在",
                details={"workflow_run_id": workflow_run_id},
            )
        return workflow_run

    def get_visible_workflow_run(
        self,
        workflow_run_id: str,
        *,
        visible_project_ids: tuple[str, ...],
    ) -> WorkflowRun:
        """按公开调用方的 Project 可见范围读取 WorkflowRun。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_visible_workflow_run(
                workflow_run_id,
                visible_project_ids=visible_project_ids,
            )
        if workflow_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRun 不存在",
                details={"workflow_run_id": workflow_run_id},
            )
        return workflow_run
