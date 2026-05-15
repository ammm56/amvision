"""workflow runtime 仓储接口定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowExecutionPolicy,
    WorkflowPreviewRun,
    WorkflowRun,
)


class WorkflowRuntimeRepository(Protocol):
    """定义 workflow runtime 三类资源的最小读写接口。"""

    def save_execution_policy(self, execution_policy: WorkflowExecutionPolicy) -> None:
        """保存一条 WorkflowExecutionPolicy。"""

        ...

    def get_execution_policy(self, execution_policy_id: str) -> WorkflowExecutionPolicy | None:
        """按 id 读取一条 WorkflowExecutionPolicy。"""

        ...

    def list_execution_policies(self, project_id: str) -> tuple[WorkflowExecutionPolicy, ...]:
        """按 Project id 列出 WorkflowExecutionPolicy。"""

        ...

    def save_preview_run(self, preview_run: WorkflowPreviewRun) -> None:
        """保存一个 WorkflowPreviewRun。"""

        ...

    def get_preview_run(self, preview_run_id: str) -> WorkflowPreviewRun | None:
        """按 id 读取一个 WorkflowPreviewRun。"""

        ...

    def list_preview_runs(self, project_id: str) -> tuple[WorkflowPreviewRun, ...]:
        """按 Project id 列出 WorkflowPreviewRun。"""

        ...

    def delete_preview_run(self, preview_run_id: str) -> None:
        """按 id 删除一个 WorkflowPreviewRun。"""

        ...

    def save_workflow_app_runtime(self, workflow_app_runtime: WorkflowAppRuntime) -> None:
        """保存一个 WorkflowAppRuntime。"""

        ...

    def get_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime | None:
        """按 id 读取一个 WorkflowAppRuntime。"""

        ...

    def list_workflow_app_runtimes(self, project_id: str) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 列出 WorkflowAppRuntime。"""

        ...

    def save_workflow_run(self, workflow_run: WorkflowRun) -> None:
        """保存一个 WorkflowRun。"""

        ...

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun | None:
        """按 id 读取一个 WorkflowRun。"""

        ...

    def list_workflow_runs(self, project_id: str) -> tuple[WorkflowRun, ...]:
        """按 Project id 列出 WorkflowRun。"""

        ...