"""Runtime 启停事务与 Worker 协调；调用方必须持有项目控制锁和生命周期锁。

本对象不复制 Runtime、revision 或 Worker 状态；所有状态从共享事务和管理器读取。
公开门面负责锁顺序、权限与组合操作，事件仅在事务提交后追加。
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Protocol
from backend.service.application.errors import ResourceConflictError, ServiceConfigurationError
from backend.service.application.workflows.app_version_service import WorkflowAppVersionService
from backend.service.application.workflows.worker.manager import WorkflowRuntimeWorkerManager
from backend.service.application.workflows.runtime.app_runtimes import apply_worker_state, with_runtime_resource_updated_by
from backend.service.application.workflows.runtime.metadata import now_isoformat as _now_isoformat
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class RuntimeEventSink(Protocol):
    """提交后的运行实例事件端口，沿用门面的顺序与存储机制。"""

    def __call__(self, runtime: WorkflowAppRuntime, *, event_type: str, message: str) -> object:
        """追加指定 Runtime 状态的事件。"""
        ...


@dataclass(frozen=True)
class WorkflowRuntimeLifecycle:
    """显式接收共享依赖；不拥有第二份锁或运行状态。

    worker_manager 复用唯一 Worker 管理器；open_unit_of_work 保持既有事务边界；
    get_runtime 读取权威状态；build_version_service 解析版本；require_contract
    校验可调用契约；append_event 负责提交后的事件写入。
    """

    worker_manager: WorkflowRuntimeWorkerManager
    open_unit_of_work: Callable[[], AbstractContextManager[SqlAlchemyUnitOfWork]]
    get_runtime: Callable[[str], WorkflowAppRuntime]
    build_version_service: Callable[[], WorkflowAppVersionService]
    require_contract: Callable[[dict[str, object]], None]
    append_event: RuntimeEventSink

    def start(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """在已持有本地生命周期锁时启动 Runtime worker。"""

        workflow_app_runtime = self.get_runtime(workflow_runtime_id)
        if workflow_app_runtime.desired_revision_id is None:
            raise ResourceConflictError(
                "WorkflowAppRuntime 尚未选择可启动的版本",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        with self.open_unit_of_work() as unit_of_work:
            desired_revision = (
                unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                    workflow_app_runtime.desired_revision_id
                )
            )
        if desired_revision is None or desired_revision.state not in {
            "staged",
            "active",
        }:
            raise ResourceConflictError(
                "WorkflowAppRuntime 的目标 revision 当前不可启动",
                details={
                    "desired_revision_id": workflow_app_runtime.desired_revision_id,
                    "revision_state": (
                        desired_revision.state if desired_revision is not None else None
                    ),
                },
            )
        starting_runtime = replace(
            workflow_app_runtime,
            desired_state="running",
            observed_state="starting",
            updated_at=_now_isoformat(),
            heartbeat_at=None,
            worker_instance_id=None,
            worker_process_id=None,
            loaded_snapshot_fingerprint=None,
            last_error=None,
            health_summary={},
            metadata=with_runtime_resource_updated_by(
                dict(workflow_app_runtime.metadata),
                updated_by,
            ),
        )
        with self.open_unit_of_work() as unit_of_work:
            updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                starting_runtime,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_revision_id=desired_revision.workflow_runtime_revision_id,
                expected_worker_instance_id=workflow_app_runtime.worker_instance_id,
                expected_desired_state=workflow_app_runtime.desired_state,
                expected_observed_state=workflow_app_runtime.observed_state,
            )
            if not updated:
                raise ResourceConflictError(
                    "WorkflowAppRuntime 状态已发生变化，不能启动"
                )
            unit_of_work.commit()
        try:
            version_service = self.build_version_service()
            desired_version = version_service.get_version_by_id(
                project_id=workflow_app_runtime.project_id,
                workflow_app_version_id=desired_revision.workflow_app_version_id,
            )
            desired_detail = version_service.get_version_detail(
                project_id=desired_version.project_id,
                application_id=desired_version.application_id,
                workflow_app_version_id=desired_version.workflow_app_version_id,
            )
            self.require_contract(desired_detail.contract)
            runtime_state = self.worker_manager.start_runtime(
                starting_runtime,
                workflow_runtime_revision_id=(
                    desired_revision.workflow_runtime_revision_id
                ),
                runtime_generation=desired_revision.generation,
                expected_snapshot_fingerprint=(
                    desired_revision.expected_snapshot_fingerprint
                ),
            )
            if runtime_state.observed_state != "running":
                raise ServiceConfigurationError(
                    "workflow runtime worker 未进入 running 状态",
                    details={"observed_state": runtime_state.observed_state},
                )
            if (
                runtime_state.loaded_snapshot_fingerprint
                != desired_revision.expected_snapshot_fingerprint
            ):
                self.worker_manager.stop_runtime(workflow_runtime_id)
                raise ServiceConfigurationError(
                    "workflow runtime worker 加载的快照指纹不匹配",
                    details={
                        "expected": desired_revision.expected_snapshot_fingerprint,
                        "actual": runtime_state.loaded_snapshot_fingerprint,
                    },
                )
        except Exception as error:
            failed_runtime = replace(
                starting_runtime,
                desired_state="stopped",
                observed_state="failed",
                updated_at=_now_isoformat(),
                worker_instance_id=None,
                worker_process_id=None,
                last_error=str(error),
            )
            with self.open_unit_of_work() as unit_of_work:
                failed_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                    failed_runtime,
                    expected_generation=desired_revision.generation,
                    expected_revision_id=(
                        desired_revision.workflow_runtime_revision_id
                    ),
                    expected_worker_instance_id=None,
                    expected_desired_state="running",
                    expected_observed_state="starting",
                )
                if failed_updated and desired_revision.state == "staged":
                    unit_of_work.workflow_runtime.update_workflow_runtime_revision_state(
                        desired_revision.workflow_runtime_revision_id,
                        state="failed",
                        activated_at=None,
                        failed_at=_now_isoformat(),
                        error=str(error)[:2048],
                    )
                unit_of_work.commit()
            if failed_updated:
                self.append_event(
                    failed_runtime,
                    event_type="runtime.failed",
                    message="workflow app runtime 目标版本启动失败",
                )
            raise
        updated_runtime = apply_worker_state(
            replace(
                starting_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
            ),
            runtime_state,
        )
        activated_at = _now_isoformat()
        updated_runtime = replace(
            updated_runtime,
            active_revision_id=desired_revision.workflow_runtime_revision_id,
            desired_revision_id=desired_revision.workflow_runtime_revision_id,
        )
        with self.open_unit_of_work() as unit_of_work:
            activated = unit_of_work.workflow_runtime.activate_workflow_app_runtime_revision_if_current(
                updated_runtime,
                expected_generation=desired_revision.generation,
                expected_revision_id=desired_revision.workflow_runtime_revision_id,
                expected_worker_instance_id=None,
            )
            if not activated:
                unit_of_work.rollback()
                self.worker_manager.stop_runtime(workflow_runtime_id)
                raise ResourceConflictError(
                    "WorkflowAppRuntime 在 worker 启动期间已发生变化"
                )
            if desired_revision.state == "staged":
                if (
                    workflow_app_runtime.active_revision_id is not None
                    and workflow_app_runtime.active_revision_id
                    != desired_revision.workflow_runtime_revision_id
                ):
                    old_revision = (
                        unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                            workflow_app_runtime.active_revision_id
                        )
                    )
                    if old_revision is not None:
                        unit_of_work.workflow_runtime.update_workflow_runtime_revision_state(
                            old_revision.workflow_runtime_revision_id,
                            state="retired",
                            activated_at=old_revision.activated_at,
                            failed_at=old_revision.failed_at,
                            error=old_revision.error,
                        )
                unit_of_work.workflow_runtime.update_workflow_runtime_revision_state(
                    desired_revision.workflow_runtime_revision_id,
                    state="active",
                    activated_at=activated_at,
                    failed_at=None,
                    error=None,
                )
            unit_of_work.commit()
        self.append_event(
            updated_runtime,
            event_type="runtime.started"
            if updated_runtime.observed_state == "running"
            else "runtime.failed",
            message=(
                "workflow app runtime 已启动"
                if updated_runtime.observed_state == "running"
                else "workflow app runtime 启动失败"
            ),
        )
        return updated_runtime


    def stop(
        self,
        workflow_runtime_id: str,
        *,
        updated_by: str | None = None,
    ) -> WorkflowAppRuntime:
        """在已持有本地生命周期锁时停止 Runtime worker。"""

        workflow_app_runtime = self.get_runtime(workflow_runtime_id)
        stopping_runtime = replace(
            workflow_app_runtime,
            desired_state="stopped",
            observed_state="stopping",
            updated_at=_now_isoformat(),
            metadata=with_runtime_resource_updated_by(
                dict(workflow_app_runtime.metadata),
                updated_by,
            ),
        )
        expected_revision_id = (
            workflow_app_runtime.desired_revision_id
            or workflow_app_runtime.active_revision_id
        )
        if expected_revision_id is None:
            raise ResourceConflictError("WorkflowAppRuntime 缺少可停止的 revision")
        with self.open_unit_of_work() as unit_of_work:
            updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                stopping_runtime,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_revision_id=expected_revision_id,
                expected_worker_instance_id=workflow_app_runtime.worker_instance_id,
                expected_desired_state=workflow_app_runtime.desired_state,
                expected_observed_state=workflow_app_runtime.observed_state,
            )
            if not updated:
                raise ResourceConflictError(
                    "WorkflowAppRuntime 状态已发生变化，不能停止"
                )
            unit_of_work.commit()
        runtime_state = self.worker_manager.stop_runtime(workflow_runtime_id)
        updated_runtime = apply_worker_state(
            replace(
                stopping_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_stopped_at=_now_isoformat(),
            ),
            runtime_state,
        )
        updated_runtime = replace(
            updated_runtime,
            worker_instance_id=None,
            worker_process_id=None,
            heartbeat_at=runtime_state.heartbeat_at,
        )
        with self.open_unit_of_work() as unit_of_work:
            updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                updated_runtime,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_revision_id=expected_revision_id,
                expected_worker_instance_id=workflow_app_runtime.worker_instance_id,
                expected_desired_state="stopped",
                expected_observed_state="stopping",
            )
            if not updated:
                raise ResourceConflictError(
                    "WorkflowAppRuntime 在 worker 停止期间已发生变化"
                )
            unit_of_work.commit()
        self.append_event(
            updated_runtime,
            event_type="runtime.stopped",
            message="workflow app runtime 已停止",
        )
        return updated_runtime
