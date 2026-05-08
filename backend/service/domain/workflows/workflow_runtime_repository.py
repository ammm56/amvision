"""workflow runtime 仓储接口定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowPreviewRun,
    WorkflowRun,
)


class WorkflowRuntimeRepository(Protocol):
    """定义 workflow runtime 三类资源的最小读写接口。"""

    def save_preview_run(self, preview_run: WorkflowPreviewRun) -> None:
        """保存一个 WorkflowPreviewRun。"""

        ...

    def get_preview_run(self, preview_run_id: str) -> WorkflowPreviewRun | None:
        """按 id 读取一个 WorkflowPreviewRun。"""

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