"""workflow runtime 仓储接口定义。"""

from __future__ import annotations

from typing import Protocol

from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowApplicationLifecycle,
    WorkflowAppRuntime,
    WorkflowAppVersion,
    WorkflowExecutionPolicy,
    WorkflowPreviewRun,
    WorkflowRuntimeRevision,
    WorkflowRun,
)


class WorkflowRuntimeRepository(Protocol):
    """定义 workflow 版本、Application lifecycle 和 runtime 资源读写接口。"""

    def save_execution_policy(self, execution_policy: WorkflowExecutionPolicy) -> None:
        """保存一条 WorkflowExecutionPolicy。"""

        ...

    def get_execution_policy(
        self, execution_policy_id: str
    ) -> WorkflowExecutionPolicy | None:
        """按 id 读取一条 WorkflowExecutionPolicy。"""

        ...

    def list_execution_policies(
        self, project_id: str
    ) -> tuple[WorkflowExecutionPolicy, ...]:
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

    def count_preview_run_states_by_project(self, project_id: str) -> dict[str, int]:
        """按 Project id 聚合 WorkflowPreviewRun 状态数量。"""

        ...

    def delete_preview_run(self, preview_run_id: str) -> None:
        """按 id 删除一个 WorkflowPreviewRun。"""

        ...

    def save_workflow_app_runtime(
        self, workflow_app_runtime: WorkflowAppRuntime
    ) -> None:
        """创建一个 WorkflowAppRuntime；既有正式记录必须使用字段级 CAS。"""

        ...

    def replace_workflow_app_runtime_for_migration(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> None:
        """仅供启动迁移完整替换一个既有 WorkflowAppRuntime。"""

        ...

    def get_workflow_app_runtime(
        self, workflow_runtime_id: str
    ) -> WorkflowAppRuntime | None:
        """按 id 读取一个 WorkflowAppRuntime。"""

        ...

    def list_workflow_app_runtimes(
        self,
        project_id: str,
        *,
        application_id: str | None = None,
        application_ids: tuple[str, ...] | None = None,
    ) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 和可选 Application 过滤条件列出 Runtime。"""

        ...

    def list_all_workflow_app_runtimes(self) -> tuple[WorkflowAppRuntime, ...]:
        """跨 Project 列出全部 WorkflowAppRuntime，供幂等迁移使用。"""

        ...

    def compare_and_set_workflow_app_runtime_revision(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        expected_generation: int,
    ) -> bool:
        """按 generation CAS 更新 Runtime 的版本选择指针。"""

        ...

    def update_workflow_app_runtime_state_if_current(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        expected_generation: int,
        expected_revision_id: str | None,
        expected_worker_instance_id: str | None,
        expected_desired_state: str | None = None,
        expected_observed_state: str | None = None,
    ) -> bool:
        """仅在 revision、generation 和 worker epoch 仍匹配时更新运行状态。"""

        ...

    def activate_workflow_app_runtime_revision_if_current(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        expected_generation: int,
        expected_revision_id: str,
        expected_worker_instance_id: str | None,
    ) -> bool:
        """仅在目标 revision 未变化时激活已启动的 worker。"""

        ...

    def list_workflow_app_runtimes_by_desired_state(
        self,
        desired_state: str,
    ) -> tuple[WorkflowAppRuntime, ...]:
        """跨 Project 列出指定期望状态的 WorkflowAppRuntime。"""

        ...

    def delete_workflow_app_runtime(self, workflow_runtime_id: str) -> None:
        """按 id 删除一个 WorkflowAppRuntime。"""

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

    def list_workflow_runs_by_runtime(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRun, ...]:
        """按稳定 Runtime id 列出全部历史 WorkflowRun。"""

        ...

    def count_workflow_run_states_by_project(self, project_id: str) -> dict[str, int]:
        """按 Project id 聚合 WorkflowRun 状态数量。"""

        ...

    def list_active_workflow_runs_for_runtime(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRun, ...]:
        """列出 Runtime 当前未结束的正式运行。"""

        ...

    def add_workflow_app_version(
        self,
        workflow_app_version: WorkflowAppVersion,
        *,
        reserve_content_fingerprint: bool = True,
    ) -> None:
        """新增一条不可变版本，并可原子占用默认内容去重键。"""

        ...

    def update_workflow_app_version_state(
        self,
        workflow_app_version_id: str,
        *,
        state: str,
        completed_at: str | None,
        error: str | None,
    ) -> None:
        """只更新版本发布状态和诊断字段。"""

        ...

    def add_workflow_application_lifecycle(
        self, lifecycle: WorkflowApplicationLifecycle
    ) -> None:
        """新增一条 Application lifecycle；既有 tombstone 不得覆盖。"""

        ...

    def get_workflow_application_lifecycle(
        self, project_id: str, application_id: str
    ) -> WorkflowApplicationLifecycle | None:
        """读取一条 Application lifecycle。"""

        ...

    def try_claim_workflow_application_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_generation: int,
        operation_state: str,
        operation_id: str,
        updated_at: str,
        allow_deleted: bool,
    ) -> bool:
        """以 generation CAS 尝试占用 Application 写操作状态门。"""

        ...

    def complete_workflow_application_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_generation: int,
        operation_state: str,
        operation_id: str,
        updated_at: str,
        deleted: bool,
    ) -> bool:
        """仅由当前 operation 完成或恢复 Application 状态门。"""

        ...

    def delete_idle_workflow_application_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_generation: int,
    ) -> bool:
        """删除已释放的临时 lifecycle，避免高频资源 id 长期累积。"""

        ...

    def list_claimed_workflow_application_lifecycles(
        self,
    ) -> tuple[WorkflowApplicationLifecycle, ...]:
        """列出启动期需要收敛的未完成 Application 操作。"""

        ...

    def compare_and_set_workflow_app_version_state(
        self,
        workflow_app_version_id: str,
        *,
        expected_state: str,
        target_state: str,
    ) -> bool:
        """按预期状态原子切换版本生命周期状态。"""

        ...

    def fence_published_workflow_app_version(
        self,
        workflow_app_version_id: str,
    ) -> bool:
        """条件占用 published 版本行，供同一事务内创建 Runtime 引用。"""

        ...

    def get_workflow_app_version(
        self, workflow_app_version_id: str
    ) -> WorkflowAppVersion | None:
        """按 id 读取 WorkflowAppVersion。"""

        ...

    def list_workflow_app_versions(
        self, project_id: str, application_id: str, *, include_incomplete: bool = False
    ) -> tuple[WorkflowAppVersion, ...]:
        """按 Application 列出版本。"""

        ...

    def list_incomplete_workflow_app_versions(self) -> tuple[WorkflowAppVersion, ...]:
        """跨 Project 列出 publishing 状态版本，供启动恢复使用。"""

        ...

    def get_latest_workflow_app_version_number(
        self, project_id: str, application_id: str
    ) -> int:
        """读取 Application 当前最大内部版本号。"""

        ...

    def get_published_workflow_app_version_by_fingerprint(
        self, project_id: str, application_id: str, content_fingerprint: str
    ) -> WorkflowAppVersion | None:
        """按内容指纹查找已发布版本。"""

        ...

    def get_claimed_workflow_app_version_by_fingerprint(
        self, project_id: str, application_id: str, content_fingerprint: str
    ) -> WorkflowAppVersion | None:
        """读取当前持有默认内容去重键的版本。"""

        ...

    def add_workflow_runtime_revision(
        self, workflow_runtime_revision: WorkflowRuntimeRevision
    ) -> None:
        """新增一条不可变 Runtime revision。"""

        ...

    def get_workflow_runtime_revision(
        self, workflow_runtime_revision_id: str
    ) -> WorkflowRuntimeRevision | None:
        """按 id 读取 Runtime revision。"""

        ...

    def update_workflow_runtime_revision_state(
        self,
        workflow_runtime_revision_id: str,
        *,
        state: str,
        activated_at: str | None,
        failed_at: str | None,
        error: str | None,
    ) -> None:
        """只更新 revision 生命周期状态和诊断字段。"""

        ...

    def list_workflow_runtime_revisions(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRuntimeRevision, ...]:
        """按 Runtime 列出 revision。"""

        ...
