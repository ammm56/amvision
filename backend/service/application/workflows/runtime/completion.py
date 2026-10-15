"""Workflow 异步执行终态提交；Worker 管理器调度回调，仓储负责 epoch 核对。

本组件只使用注入的事务、事件与结果缓存端口，不创建第二份运行状态。
"""
from __future__ import annotations
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Protocol
from backend.contracts.workflows.resource_semantics import WORKFLOW_RUN_TERMINAL_STATES
from backend.service.application.errors import ServiceError, ResourceConflictError, OperationTimeoutError
from backend.service.application.workflows.worker.messages import WorkflowRuntimeWorkerRunResult
from backend.service.application.workflows.runtime.app_runtimes import apply_worker_state
from backend.service.application.workflows.runtime.policies import WORKFLOW_RUN_RECORD_MODE_FULL, WORKFLOW_RUN_RECORD_MODE_MINIMAL, resolve_workflow_run_record_mode
from backend.service.application.workflows.runtime.metadata import now_isoformat as _now_isoformat, build_minimal_workflow_run_record as _build_minimal_workflow_run_record
from backend.service.application.workflows.runtime.persistence import apply_workflow_run_result
from backend.service.application.workflows.trigger_sources.output_delivery import PreparedTriggerResult, build_prepared_result_outputs
from backend.service.application.workflows.worker.health import WorkflowRuntimeWorkerState
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime, WorkflowRun, WorkflowExecutionPolicy
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class RunEventSink(Protocol):
    """事务提交后的运行事件入口。"""
    def __call__(self, run: WorkflowRun, *, event_type: str, message: str) -> object:
        """追加已提交终态对应的事件。"""
        ...


class RuntimeEventSink(Protocol):
    """事务提交后的 Runtime 事件入口。"""
    def __call__(self, runtime: WorkflowAppRuntime, *, event_type: str, message: str, payload: dict[str, object]) -> object:
        """追加实际更新后的 Runtime 事件。"""
        ...


def _with_prepared_async_outputs(
    worker_result: WorkflowRuntimeWorkerRunResult,
) -> WorkflowRuntimeWorkerRunResult:
    """让异步查询只持久化 selected JSON 与稳定 ObjectStore locator。"""

    if not isinstance(worker_result.prepared_trigger_result, dict):
        return worker_result
    prepared = PreparedTriggerResult.model_validate(
        worker_result.prepared_trigger_result
    )
    return replace(
        worker_result,
        outputs=build_prepared_result_outputs(prepared),
    )


@dataclass(frozen=True)
class WorkflowRunCompletion:
    """把执行终态转换、持久化与提交后事件集中在一个无状态协调边界。

    open_unit_of_work 提供事务；load_execution_policy 解析记录策略；remember_outputs
    使用门面的既有缓存；append_run_event/append_runtime_event 写提交后的事件；
    event_type_for_state/message_for_state 保持现有事件名称与说明。
    """
    open_unit_of_work: Callable[[], AbstractContextManager[SqlAlchemyUnitOfWork]]
    load_execution_policy: Callable[[WorkflowAppRuntime], WorkflowExecutionPolicy]
    remember_outputs: Callable[[str, dict[str, object]], None]
    append_run_event: RunEventSink
    append_runtime_event: RuntimeEventSink
    event_type_for_state: Callable[[str], str]
    message_for_state: Callable[[str], str]

    def _finish_async_workflow_run_with_result(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        worker_result: WorkflowRuntimeWorkerRunResult,
    ) -> None:
        """把异步 WorkflowRun 的完成结果回写到持久化层。"""

        stable_worker_result = _with_prepared_async_outputs(worker_result)
        with self.open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            if workflow_run is None or workflow_app_runtime is None or workflow_run.state in WORKFLOW_RUN_TERMINAL_STATES:
                return
            updated_run = apply_workflow_run_result(
                workflow_run,
                stable_worker_result,
                execution_policy=self.load_execution_policy(
                    workflow_app_runtime
                ),
            )
            record_mode = resolve_workflow_run_record_mode(updated_run.metadata)
            if record_mode == WORKFLOW_RUN_RECORD_MODE_MINIMAL:
                updated_run = _build_minimal_workflow_run_record(updated_run)
            updated_runtime = apply_worker_state(
                replace(workflow_app_runtime, updated_at=_now_isoformat()),
                worker_result.worker_state,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            runtime_updated = False
            if (
                record_mode == WORKFLOW_RUN_RECORD_MODE_FULL
                or updated_runtime.observed_state == "failed"
            ):
                if (
                    workflow_run.runtime_generation is not None
                    and workflow_run.workflow_runtime_revision_id is not None
                ):
                    runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                        updated_runtime,
                        expected_generation=workflow_run.runtime_generation,
                        expected_revision_id=(
                            workflow_run.workflow_runtime_revision_id
                        ),
                        expected_worker_instance_id=(
                            worker_result.worker_state.instance_id
                        ),
                        expected_desired_state="running",
                    )
            unit_of_work.commit()
        self.remember_outputs(
            workflow_run_id, stable_worker_result.outputs
        )
        self.append_run_event(
            updated_run,
            event_type=self.event_type_for_state(updated_run.state),
            message=self.message_for_state(updated_run.state),
        )
        if (
            runtime_updated
            and updated_runtime.observed_state == "failed"
            and workflow_app_runtime.observed_state != "failed"
        ):
            self.append_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": updated_run.state},
            )


    def _finish_async_workflow_run_failed(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        error: ServiceError,
    ) -> None:
        """把异步 WorkflowRun 的失败结果回写到持久化层。"""

        with self.open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            # 提交后事件或缓存失败可能触发 manager 的失败回调；已提交的终态不能被改写。
            if workflow_run is None or workflow_run.state in WORKFLOW_RUN_TERMINAL_STATES:
                return
            metadata = dict(workflow_run.metadata)
            if error.details:
                metadata["error_details"] = dict(error.details)
            updated_run = replace(
                workflow_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=error.message,
                metadata=metadata,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            runtime_updated = False
            if (
                workflow_app_runtime is not None
                and workflow_run.runtime_generation is not None
                and workflow_run.workflow_runtime_revision_id is not None
                and not isinstance(error, ResourceConflictError)
            ):
                error_worker_instance_id = error.details.get("worker_instance_id")
                runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                    replace(
                        workflow_app_runtime,
                        observed_state="failed",
                        updated_at=_now_isoformat(),
                        last_error=error.message,
                        health_summary={
                            "mode": "single-instance-sync",
                            "worker_state": "failed",
                            "last_error": error.message,
                        },
                    ),
                    expected_generation=workflow_run.runtime_generation,
                    expected_revision_id=(workflow_run.workflow_runtime_revision_id),
                    expected_worker_instance_id=(
                        error_worker_instance_id
                        if isinstance(error_worker_instance_id, str)
                        and error_worker_instance_id
                        else workflow_app_runtime.worker_instance_id
                    ),
                    expected_desired_state="running",
                )
            unit_of_work.commit()
            updated_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
                if runtime_updated
                else None
            )
        self.append_run_event(
            updated_run,
            event_type="run.failed",
            message="workflow run 执行失败",
        )
        if updated_runtime is not None:
            self.append_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": "run.failed"},
            )


    def _finish_async_workflow_run_timed_out(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        error: OperationTimeoutError,
    ) -> None:
        """把异步 WorkflowRun 的超时结果回写到持久化层。"""

        with self.open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            if workflow_run is None or workflow_run.state in WORKFLOW_RUN_TERMINAL_STATES:
                return
            updated_run = replace(
                workflow_run,
                state="timed_out",
                started_at=workflow_run.started_at or _now_isoformat(),
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            runtime_updated = False
            if workflow_app_runtime is not None:
                updated_runtime = self._apply_worker_failure_unless_recovered(
                    workflow_app_runtime,
                    error=error,
                )
                if (
                    workflow_run.runtime_generation is not None
                    and workflow_run.workflow_runtime_revision_id is not None
                ):
                    timeout_worker_instance_id = error.details.get("worker_instance_id")
                    runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                        updated_runtime,
                        expected_generation=workflow_run.runtime_generation,
                        expected_revision_id=(
                            workflow_run.workflow_runtime_revision_id
                        ),
                        expected_worker_instance_id=(
                            timeout_worker_instance_id
                            if isinstance(timeout_worker_instance_id, str)
                            and timeout_worker_instance_id
                            else workflow_app_runtime.worker_instance_id
                        ),
                        expected_desired_state="running",
                    )
            unit_of_work.commit()
            updated_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
                if runtime_updated
                else None
            )
        self.append_run_event(
            updated_run,
            event_type="run.timed_out",
            message="workflow run 已超时",
        )
        if updated_runtime is not None and updated_runtime.observed_state == "failed":
            self.append_runtime_event(
                updated_runtime,
                event_type="runtime.failed",
                message="workflow app runtime 已进入 failed 状态",
                payload={"reason": "run.timed_out"},
            )


    def _finish_async_workflow_run_cancelled(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        runtime_state: WorkflowRuntimeWorkerState | None,
    ) -> None:
        """把异步 WorkflowRun 的取消结果回写到持久化层。"""

        with self.open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(
                workflow_run_id
            )
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            if workflow_run is None or workflow_run.state in WORKFLOW_RUN_TERMINAL_STATES:
                return
            updated_run = replace(
                workflow_run,
                state="cancelled",
                finished_at=_now_isoformat(),
                error_message="workflow run 已取消",
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            runtime_updated = False
            if workflow_app_runtime is not None and runtime_state is not None:
                if (
                    workflow_run.runtime_generation is not None
                    and workflow_run.workflow_runtime_revision_id is not None
                ):
                    runtime_updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                        apply_worker_state(
                            replace(
                                workflow_app_runtime,
                                updated_at=_now_isoformat(),
                            ),
                            runtime_state,
                        ),
                        expected_generation=workflow_run.runtime_generation,
                        expected_revision_id=(
                            workflow_run.workflow_runtime_revision_id
                        ),
                        expected_worker_instance_id=(
                            workflow_app_runtime.worker_instance_id
                        ),
                        expected_desired_state="running",
                    )
            unit_of_work.commit()
            updated_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
                if runtime_updated
                else None
            )
        self.append_run_event(
            updated_run,
            event_type="run.cancelled",
            message="workflow run 已取消",
        )
        if updated_runtime is not None and runtime_state is not None:
            self.append_runtime_event(
                updated_runtime,
                event_type=(
                    "runtime.restarted"
                    if updated_runtime.observed_state == "running"
                    else "runtime.failed"
                ),
                message=(
                    "workflow app runtime 已在取消后恢复运行"
                    if updated_runtime.observed_state == "running"
                    else "workflow app runtime 在取消后进入失败状态"
                ),
                payload={"reason": "run.cancelled"},
            )


    @staticmethod
    def _apply_worker_failure_unless_recovered(
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        error: OperationTimeoutError,
    ) -> WorkflowAppRuntime:
        """仅在超时对应的旧 worker 尚未被替换时记录 runtime 失败。

        参数：
        - workflow_app_runtime：事务内读取的最新 runtime 记录。
        - error：携带超时 worker process id 的异常。

        返回：
        - WorkflowAppRuntime：旧 worker 仍是当前代时返回 failed；监督器已经恢复为
          新进程时保留新一代 running 状态，避免迟到回调覆盖恢复结果。
        """

        failed_worker_instance_id = error.details.get("worker_instance_id")
        current_worker_instance_id = workflow_app_runtime.worker_instance_id
        failed_worker_process_id = error.details.get("worker_process_id")
        current_worker_process_id = workflow_app_runtime.worker_process_id
        recovered_by_new_worker = workflow_app_runtime.observed_state == "running" and (
            (
                isinstance(failed_worker_instance_id, str)
                and bool(failed_worker_instance_id)
                and isinstance(current_worker_instance_id, str)
                and bool(current_worker_instance_id)
                and current_worker_instance_id != failed_worker_instance_id
            )
            or (
                failed_worker_instance_id is None
                and isinstance(failed_worker_process_id, int)
                and isinstance(current_worker_process_id, int)
                and current_worker_process_id != failed_worker_process_id
            )
        )
        if recovered_by_new_worker:
            return workflow_app_runtime
        return replace(
            workflow_app_runtime,
            observed_state="failed",
            updated_at=_now_isoformat(),
            last_error=error.message,
            health_summary={
                "mode": "single-instance-sync",
                "worker_state": "failed",
                "last_error": error.message,
                "failed_worker_instance_id": failed_worker_instance_id,
                "failed_worker_process_id": failed_worker_process_id,
            },
        )
