"""workflow runtime 控制面服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.service.application.errors import InvalidRequestError, OperationTimeoutError, ResourceNotFoundError, ServiceError
from backend.service.application.workflows.runtime_worker import (
    WorkflowRuntimeAsyncRunCallbacks,
    WorkflowRuntimeWorkerInstance,
    WorkflowRuntimeWorkerManager,
    WorkflowRuntimeWorkerRunResult,
    WorkflowRuntimeWorkerState,
)
from backend.service.application.workflows.snapshot_execution import (
    WorkflowSnapshotExecutionRequest,
    WorkflowSnapshotProcessExecutor,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowPreviewRun,
    WorkflowRun,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings
from backend.nodes.node_catalog_registry import NodeCatalogRegistry


@dataclass(frozen=True)
class WorkflowPreviewRunCreateRequest:
    """描述一次 preview run 创建请求。"""

    project_id: str
    application_ref_id: str | None = None
    application: FlowApplication | None = None
    template: WorkflowGraphTemplate | None = None
    input_bindings: dict[str, object] | None = None
    execution_metadata: dict[str, object] | None = None
    timeout_seconds: int = 30


@dataclass(frozen=True)
class WorkflowAppRuntimeCreateRequest:
    """描述一次 app runtime 创建请求。"""

    project_id: str
    application_id: str
    display_name: str = ""
    request_timeout_seconds: int = 60
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class WorkflowRuntimeInvokeRequest:
    """描述一次 runtime 同步调用请求。"""

    input_bindings: dict[str, object] | None = None
    execution_metadata: dict[str, object] | None = None
    timeout_seconds: int | None = None


class WorkflowRuntimeService:
    """封装 workflow runtime 当前阶段的资源创建、调用和状态收敛逻辑。"""

    def __init__(
        self,
        *,
        settings: BackendServiceSettings,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
        worker_manager: WorkflowRuntimeWorkerManager,
    ) -> None:
        """初始化 workflow runtime 控制面服务。"""

        self.settings = settings
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.node_catalog_registry = node_catalog_registry
        self.worker_manager = worker_manager

    def create_preview_run(
        self,
        request: WorkflowPreviewRunCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowPreviewRun:
        """创建并同步执行一次 preview run。"""

        normalized_request = self._normalize_preview_request(request)
        preview_run_id = f"preview-run-{uuid4().hex}"
        application_id, application, template, source_kind = self._resolve_preview_source(normalized_request)
        application_snapshot_object_key = (
            f"workflows/runtime/preview-runs/{preview_run_id}/application.snapshot.json"
        )
        template_snapshot_object_key = (
            f"workflows/runtime/preview-runs/{preview_run_id}/template.snapshot.json"
        )
        self.dataset_storage.write_json(
            application_snapshot_object_key,
            self._with_project_metadata(application, project_id=normalized_request.project_id).model_dump(mode="json"),
        )
        self.dataset_storage.write_json(
            template_snapshot_object_key,
            template.model_dump(mode="json"),
        )

        now = _now_isoformat()
        preview_run = WorkflowPreviewRun(
            preview_run_id=preview_run_id,
            project_id=normalized_request.project_id,
            application_id=application_id,
            source_kind=source_kind,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
            state="running",
            created_at=now,
            started_at=now,
            created_by=_normalize_optional_str(created_by),
            timeout_seconds=normalized_request.timeout_seconds,
            retention_until=_future_isoformat(hours=24),
            metadata=dict(normalized_request.execution_metadata or {}),
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_preview_run(preview_run)
            unit_of_work.commit()

        try:
            execution_result = WorkflowSnapshotProcessExecutor(
                settings=self.settings,
                request_timeout_seconds=normalized_request.timeout_seconds,
            ).execute(
                WorkflowSnapshotExecutionRequest(
                    project_id=normalized_request.project_id,
                    application_id=application_id,
                    application_snapshot_object_key=application_snapshot_object_key,
                    template_snapshot_object_key=template_snapshot_object_key,
                    input_bindings=dict(normalized_request.input_bindings or {}),
                    execution_metadata=dict(normalized_request.execution_metadata or {}),
                )
            )
            preview_run = replace(
                preview_run,
                state="succeeded",
                finished_at=_now_isoformat(),
                outputs=dict(execution_result.outputs),
                template_outputs=dict(execution_result.template_outputs),
                node_records=_serialize_node_records(execution_result.node_records),
            )
        except OperationTimeoutError as exc:
            preview_run = replace(
                preview_run,
                state="timed_out",
                finished_at=_now_isoformat(),
                error_message=exc.message,
            )
        except ServiceError as exc:
            preview_run = replace(
                preview_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=exc.message,
            )

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_preview_run(preview_run)
            unit_of_work.commit()
        return preview_run

    def get_preview_run(self, preview_run_id: str) -> WorkflowPreviewRun:
        """按 id 读取一个 preview run。"""

        with self._open_unit_of_work() as unit_of_work:
            preview_run = unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
        if preview_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowPreviewRun 不存在",
                details={"preview_run_id": preview_run_id},
            )
        return preview_run

    def create_workflow_app_runtime(
        self,
        request: WorkflowAppRuntimeCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowAppRuntime:
        """创建一个最小 WorkflowAppRuntime。"""

        normalized_request = self._normalize_runtime_create_request(request)
        workflow_service = self._build_workflow_json_service()
        application_document = workflow_service.get_application(
            project_id=normalized_request.project_id,
            application_id=normalized_request.application_id,
        )
        application = self._with_project_metadata(
            application_document.application,
            project_id=normalized_request.project_id,
        )
        template_document = workflow_service.get_template(
            project_id=normalized_request.project_id,
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
        )
        workflow_runtime_id = f"workflow-runtime-{uuid4().hex}"
        application_snapshot_object_key = (
            f"workflows/runtime/app-runtimes/{workflow_runtime_id}/application.snapshot.json"
        )
        template_snapshot_object_key = (
            f"workflows/runtime/app-runtimes/{workflow_runtime_id}/template.snapshot.json"
        )
        self.dataset_storage.write_json(
            application_snapshot_object_key,
            application.model_dump(mode="json"),
        )
        self.dataset_storage.write_json(
            template_snapshot_object_key,
            template_document.template.model_dump(mode="json"),
        )
        now = _now_isoformat()
        workflow_app_runtime = WorkflowAppRuntime(
            workflow_runtime_id=workflow_runtime_id,
            project_id=normalized_request.project_id,
            application_id=normalized_request.application_id,
            display_name=normalized_request.display_name or application.display_name,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
            desired_state="stopped",
            observed_state="stopped",
            request_timeout_seconds=normalized_request.request_timeout_seconds,
            created_at=now,
            updated_at=now,
            created_by=_normalize_optional_str(created_by),
            metadata=dict(normalized_request.metadata or {}),
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(workflow_app_runtime)
            unit_of_work.commit()
        return workflow_app_runtime

    def list_workflow_app_runtimes(self, *, project_id: str) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 列出 WorkflowAppRuntime。"""

        if not project_id.strip():
            raise InvalidRequestError("查询 WorkflowAppRuntime 列表时 project_id 不能为空")
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.list_workflow_app_runtimes(project_id.strip())

    def get_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """按 id 读取一个 WorkflowAppRuntime。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
        if workflow_app_runtime is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowAppRuntime 不存在",
                details={"workflow_runtime_id": workflow_runtime_id},
            )
        return workflow_app_runtime

    def start_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """启动一个 WorkflowAppRuntime 对应的 worker。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.start_runtime(workflow_app_runtime)
        updated_runtime = self._apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="running",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
            ),
            runtime_state,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        return updated_runtime

    def stop_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """停止一个 WorkflowAppRuntime 对应的 worker。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.stop_runtime(workflow_runtime_id)
        updated_runtime = self._apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="stopped",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_stopped_at=_now_isoformat(),
            ),
            runtime_state,
        )
        updated_runtime = replace(
            updated_runtime,
            worker_process_id=None,
            heartbeat_at=runtime_state.heartbeat_at,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        return updated_runtime

    def restart_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """重启一个 WorkflowAppRuntime 对应的 worker。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。

        返回：
        - WorkflowAppRuntime：重启后的最新 runtime 记录。
        """

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        stopped_at = _now_isoformat()
        self.worker_manager.stop_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.start_runtime(workflow_app_runtime)
        updated_runtime = self._apply_worker_state(
            replace(
                workflow_app_runtime,
                desired_state="running",
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
                last_started_at=_now_isoformat(),
                last_stopped_at=stopped_at,
            ),
            runtime_state,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        return updated_runtime

    def get_workflow_app_runtime_health(self, workflow_runtime_id: str) -> WorkflowAppRuntime:
        """查询一个 WorkflowAppRuntime 的当前健康状态。"""

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        runtime_state = self.worker_manager.get_runtime_health(workflow_runtime_id)
        updated_runtime = self._apply_worker_state(
            replace(
                workflow_app_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=_now_isoformat(),
            ),
            runtime_state,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        return updated_runtime

    def list_workflow_app_runtime_instances(
        self,
        workflow_runtime_id: str,
    ) -> tuple[WorkflowRuntimeWorkerInstance, ...]:
        """列出一个 WorkflowAppRuntime 当前可观测的 instance。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。

        返回：
        - tuple[WorkflowRuntimeWorkerInstance, ...]：当前 worker manager 可观测到的 instance 摘要。
        """

        self.get_workflow_app_runtime(workflow_runtime_id)
        return self.worker_manager.list_runtime_instances(workflow_runtime_id)

    def create_workflow_run(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
    ) -> WorkflowRun:
        """为已启动的 runtime 创建一条异步 WorkflowRun。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。
        - request：异步运行请求。
        - created_by：创建主体 id。

        返回：
        - WorkflowRun：已持久化的异步 WorkflowRun，创建返回时通常为 queued。
        """

        workflow_app_runtime = self.get_workflow_app_runtime(workflow_runtime_id)
        if workflow_app_runtime.observed_state != "running" or not self.worker_manager.is_runtime_available(workflow_runtime_id):
            raise InvalidRequestError(
                "当前 WorkflowAppRuntime 未处于 running 状态",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "observed_state": workflow_app_runtime.observed_state,
                },
            )

        normalized_request = self._normalize_runtime_invoke_request(request)
        metadata = dict(normalized_request.execution_metadata or {})
        metadata.setdefault("trigger_source", "async-invoke")
        now = _now_isoformat()
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            state="queued",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=normalized_request.timeout_seconds or workflow_app_runtime.request_timeout_seconds,
            input_payload=dict(normalized_request.input_bindings or {}),
            metadata=metadata,
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.commit()

        try:
            self.worker_manager.submit_async_run(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id=workflow_run.workflow_run_id,
                input_bindings=dict(normalized_request.input_bindings or {}),
                execution_metadata=metadata,
                timeout_seconds=workflow_run.requested_timeout_seconds,
                callbacks=self._build_async_run_callbacks(
                    workflow_app_runtime.workflow_runtime_id,
                    workflow_run.workflow_run_id,
                ),
            )
        except ServiceError as error:
            workflow_run = replace(
                workflow_run,
                state="failed",
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            with self._open_unit_of_work() as unit_of_work:
                unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
                unit_of_work.commit()
        return workflow_run

    def invoke_workflow_app_runtime(
        self,
        workflow_runtime_id: str,
        request: WorkflowRuntimeInvokeRequest,
        *,
        created_by: str | None,
    ) -> WorkflowRun:
        """通过已启动的 runtime 发起一次同步调用。"""

        workflow_app_runtime = self.get_workflow_app_runtime_health(workflow_runtime_id)
        if workflow_app_runtime.observed_state != "running":
            raise InvalidRequestError(
                "当前 WorkflowAppRuntime 未处于 running 状态",
                details={
                    "workflow_runtime_id": workflow_runtime_id,
                    "observed_state": workflow_app_runtime.observed_state,
                },
            )

        normalized_request = self._normalize_runtime_invoke_request(request)
        now = _now_isoformat()
        workflow_run = WorkflowRun(
            workflow_run_id=f"workflow-run-{uuid4().hex}",
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            state="dispatching",
            created_at=now,
            created_by=_normalize_optional_str(created_by),
            requested_timeout_seconds=normalized_request.timeout_seconds or workflow_app_runtime.request_timeout_seconds,
            input_payload=dict(normalized_request.input_bindings or {}),
            metadata=dict(normalized_request.execution_metadata or {}),
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.commit()

        try:
            worker_result = self.worker_manager.invoke_runtime(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id=workflow_run.workflow_run_id,
                input_bindings=dict(normalized_request.input_bindings or {}),
                execution_metadata=dict(normalized_request.execution_metadata or {}),
                timeout_seconds=workflow_run.requested_timeout_seconds,
            )
            workflow_run = self._apply_run_result(workflow_run, worker_result)
            workflow_app_runtime = self._apply_worker_state(
                replace(workflow_app_runtime, updated_at=_now_isoformat()),
                worker_result.worker_state,
            )
        except OperationTimeoutError as exc:
            workflow_run = replace(
                workflow_run,
                state="timed_out",
                started_at=workflow_run.started_at or now,
                finished_at=_now_isoformat(),
                error_message=exc.message,
            )
            workflow_app_runtime = replace(
                workflow_app_runtime,
                observed_state="failed",
                updated_at=_now_isoformat(),
                last_error=exc.message,
                health_summary={
                    "mode": "single-instance-sync",
                    "worker_state": "failed",
                    "last_error": exc.message,
                },
            )

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.workflow_runtime.save_workflow_app_runtime(workflow_app_runtime)
            unit_of_work.commit()
        return workflow_run

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        """按 id 读取一个 WorkflowRun。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
        if workflow_run is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowRun 不存在",
                details={"workflow_run_id": workflow_run_id},
            )
        return workflow_run

    def cancel_workflow_run(self, workflow_run_id: str, *, cancelled_by: str | None) -> WorkflowRun:
        """取消一条异步 WorkflowRun。

        参数：
        - workflow_run_id：目标 WorkflowRun id。
        - cancelled_by：取消主体 id。

        返回：
        - WorkflowRun：取消后的最新 WorkflowRun。
        """

        workflow_run = self.get_workflow_run(workflow_run_id)
        if workflow_run.state in {"succeeded", "failed", "timed_out", "cancelled"}:
            return workflow_run

        cancel_metadata = dict(workflow_run.metadata)
        cancel_metadata["cancel_requested_at"] = _now_isoformat()
        normalized_cancelled_by = _normalize_optional_str(cancelled_by)
        if normalized_cancelled_by is not None:
            cancel_metadata["cancelled_by"] = normalized_cancelled_by
        workflow_run = replace(workflow_run, metadata=cancel_metadata)
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_runtime.save_workflow_run(workflow_run)
            unit_of_work.commit()

        self.worker_manager.cancel_async_run(
            workflow_run_id,
            timeout_seconds=min(max(float(workflow_run.requested_timeout_seconds), 1.0), 10.0),
        )
        return self.get_workflow_run(workflow_run_id)

    def _resolve_preview_source(
        self,
        request: WorkflowPreviewRunCreateRequest,
    ) -> tuple[str, FlowApplication, WorkflowGraphTemplate, str]:
        """解析 preview run 的执行来源。"""

        workflow_service = self._build_workflow_json_service()
        if request.application_ref_id is not None:
            application_document = workflow_service.get_application(
                project_id=request.project_id,
                application_id=request.application_ref_id,
            )
            application = self._with_project_metadata(
                application_document.application,
                project_id=request.project_id,
            )
            template_document = workflow_service.get_template(
                project_id=request.project_id,
                template_id=application.template_ref.template_id,
                template_version=application.template_ref.template_version,
            )
            return (
                request.application_ref_id,
                application,
                template_document.template,
                "saved-application",
            )
        if request.application is not None and request.template is not None:
            application = self._with_project_metadata(request.application, project_id=request.project_id)
            workflow_service.validate_application(
                project_id=request.project_id,
                application=application,
                template_override=request.template,
            )
            return (
                application.application_id,
                application,
                request.template,
                "inline-snapshot",
            )
        raise InvalidRequestError("preview run 需要 application_ref_id 或 application + template")

    def _apply_worker_state(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        runtime_state: WorkflowRuntimeWorkerState,
    ) -> WorkflowAppRuntime:
        """把 worker 返回状态回写到 WorkflowAppRuntime。"""

        return replace(
            workflow_app_runtime,
            observed_state=runtime_state.observed_state,
            worker_process_id=runtime_state.process_id,
            heartbeat_at=runtime_state.heartbeat_at,
            loaded_snapshot_fingerprint=runtime_state.loaded_snapshot_fingerprint,
            last_error=runtime_state.last_error,
            health_summary=dict(runtime_state.health_summary),
        )

    def _apply_run_result(
        self,
        workflow_run: WorkflowRun,
        worker_result: WorkflowRuntimeWorkerRunResult,
    ) -> WorkflowRun:
        """把 worker 返回的执行结果回写到 WorkflowRun。"""

        metadata = dict(workflow_run.metadata)
        if worker_result.error_details:
            metadata["error_details"] = dict(worker_result.error_details)
        return replace(
            workflow_run,
            state=worker_result.state,
            started_at=workflow_run.started_at or _now_isoformat(),
            finished_at=_now_isoformat(),
            assigned_process_id=worker_result.worker_state.process_id,
            outputs=dict(worker_result.outputs),
            template_outputs=dict(worker_result.template_outputs),
            node_records=tuple(worker_result.node_records),
            error_message=worker_result.error_message,
            metadata=metadata,
        )

    def _build_async_run_callbacks(
        self,
        workflow_runtime_id: str,
        workflow_run_id: str,
    ) -> WorkflowRuntimeAsyncRunCallbacks:
        """构造异步 WorkflowRun 的后台线程回调。"""

        return WorkflowRuntimeAsyncRunCallbacks(
            on_started=lambda: self._mark_async_workflow_run_started(workflow_run_id),
            on_completed=lambda worker_result: self._finish_async_workflow_run_with_result(
                workflow_run_id,
                workflow_runtime_id,
                worker_result,
            ),
            on_cancelled=lambda runtime_state: self._finish_async_workflow_run_cancelled(
                workflow_run_id,
                workflow_runtime_id,
                runtime_state,
            ),
            on_failed=lambda error: self._finish_async_workflow_run_failed(
                workflow_run_id,
                workflow_runtime_id,
                error,
            ),
            on_timed_out=lambda error: self._finish_async_workflow_run_timed_out(
                workflow_run_id,
                workflow_runtime_id,
                error,
            ),
        )

    def _mark_async_workflow_run_started(self, workflow_run_id: str) -> None:
        """把异步 WorkflowRun 从 queued 推进到 running。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            if workflow_run is None or workflow_run.state != "queued":
                return
            unit_of_work.workflow_runtime.save_workflow_run(
                replace(
                    workflow_run,
                    state="running",
                    started_at=workflow_run.started_at or _now_isoformat(),
                )
            )
            unit_of_work.commit()

    def _finish_async_workflow_run_with_result(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        worker_result: WorkflowRuntimeWorkerRunResult,
    ) -> None:
        """把异步 WorkflowRun 的完成结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None or workflow_app_runtime is None:
                return
            updated_run = self._apply_run_result(workflow_run, worker_result)
            updated_runtime = self._apply_worker_state(
                replace(workflow_app_runtime, updated_at=_now_isoformat()),
                worker_result.worker_state,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()

    def _finish_async_workflow_run_failed(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        error: ServiceError,
    ) -> None:
        """把异步 WorkflowRun 的失败结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None:
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
            if workflow_app_runtime is not None:
                unit_of_work.workflow_runtime.save_workflow_app_runtime(
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
                    )
                )
            unit_of_work.commit()

    def _finish_async_workflow_run_timed_out(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        error: OperationTimeoutError,
    ) -> None:
        """把异步 WorkflowRun 的超时结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None:
                return
            updated_run = replace(
                workflow_run,
                state="timed_out",
                started_at=workflow_run.started_at or _now_isoformat(),
                finished_at=_now_isoformat(),
                error_message=error.message,
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            if workflow_app_runtime is not None:
                unit_of_work.workflow_runtime.save_workflow_app_runtime(
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
                    )
                )
            unit_of_work.commit()

    def _finish_async_workflow_run_cancelled(
        self,
        workflow_run_id: str,
        workflow_runtime_id: str,
        runtime_state: WorkflowRuntimeWorkerState | None,
    ) -> None:
        """把异步 WorkflowRun 的取消结果回写到持久化层。"""

        with self._open_unit_of_work() as unit_of_work:
            workflow_run = unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_run is None:
                return
            updated_run = replace(
                workflow_run,
                state="cancelled",
                finished_at=_now_isoformat(),
                error_message="workflow run 已取消",
            )
            unit_of_work.workflow_runtime.save_workflow_run(updated_run)
            if workflow_app_runtime is not None and runtime_state is not None:
                unit_of_work.workflow_runtime.save_workflow_app_runtime(
                    self._apply_worker_state(
                        replace(workflow_app_runtime, updated_at=_now_isoformat()),
                        runtime_state,
                    )
                )
            unit_of_work.commit()

    def _build_workflow_json_service(self) -> LocalWorkflowJsonService:
        """构建 workflow JSON 服务。"""

        return LocalWorkflowJsonService(
            dataset_storage=self.dataset_storage,
            node_catalog_registry=self.node_catalog_registry,
        )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并管理一个请求级 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()

    @staticmethod
    def _with_project_metadata(application: FlowApplication, *, project_id: str) -> FlowApplication:
        """把 project_id 写入 application metadata，供 runtime snapshot 读取。"""

        metadata = dict(application.metadata)
        metadata["project_id"] = project_id
        return application.model_copy(update={"metadata": metadata})

    @staticmethod
    def _normalize_preview_request(request: WorkflowPreviewRunCreateRequest) -> WorkflowPreviewRunCreateRequest:
        """规范化 preview run 创建请求。"""

        project_id = request.project_id.strip()
        if not project_id:
            raise InvalidRequestError("project_id 不能为空")
        if request.timeout_seconds <= 0:
            raise InvalidRequestError("timeout_seconds 必须大于 0")
        application_ref_id = _normalize_optional_str(request.application_ref_id)
        return WorkflowPreviewRunCreateRequest(
            project_id=project_id,
            application_ref_id=application_ref_id,
            application=request.application,
            template=request.template,
            input_bindings=dict(request.input_bindings or {}),
            execution_metadata=dict(request.execution_metadata or {}),
            timeout_seconds=request.timeout_seconds,
        )

    @staticmethod
    def _normalize_runtime_create_request(
        request: WorkflowAppRuntimeCreateRequest,
    ) -> WorkflowAppRuntimeCreateRequest:
        """规范化 app runtime 创建请求。"""

        project_id = request.project_id.strip()
        application_id = request.application_id.strip()
        if not project_id:
            raise InvalidRequestError("project_id 不能为空")
        if not application_id:
            raise InvalidRequestError("application_id 不能为空")
        if request.request_timeout_seconds <= 0:
            raise InvalidRequestError("request_timeout_seconds 必须大于 0")
        return WorkflowAppRuntimeCreateRequest(
            project_id=project_id,
            application_id=application_id,
            display_name=request.display_name.strip(),
            request_timeout_seconds=request.request_timeout_seconds,
            metadata=dict(request.metadata or {}),
        )

    @staticmethod
    def _normalize_runtime_invoke_request(
        request: WorkflowRuntimeInvokeRequest,
    ) -> WorkflowRuntimeInvokeRequest:
        """规范化 runtime invoke 请求。"""

        if request.timeout_seconds is not None and request.timeout_seconds <= 0:
            raise InvalidRequestError("timeout_seconds 必须大于 0")
        return WorkflowRuntimeInvokeRequest(
            input_bindings=dict(request.input_bindings or {}),
            execution_metadata=dict(request.execution_metadata or {}),
            timeout_seconds=request.timeout_seconds,
        )


def _serialize_node_records(node_records: tuple[object, ...]) -> tuple[dict[str, object], ...]:
    """把节点执行记录转换为稳定 JSON 结构。"""

    serialized: list[dict[str, object]] = []
    for item in node_records:
        serialized.append(
            {
                "node_id": getattr(item, "node_id", ""),
                "node_type_id": getattr(item, "node_type_id", ""),
                "runtime_kind": getattr(item, "runtime_kind", ""),
                "outputs": dict(getattr(item, "outputs", {}) or {}),
            }
        )
    return tuple(serialized)


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _future_isoformat(*, hours: int) -> str:
    """返回若干小时后的 UTC 时间文本。"""

    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None