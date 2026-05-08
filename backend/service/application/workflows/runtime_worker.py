"""workflow runtime worker 管理器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing.queues import Queue
from pathlib import Path
from queue import Empty
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any
from uuid import uuid4
import multiprocessing

from sqlalchemy.engine import URL, make_url

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.queue import LocalFileQueueBackend
from backend.service.application.errors import (
    OperationCancelledError,
    OperationTimeoutError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
    WorkflowSnapshotExecutionRequest,
    build_snapshot_fingerprint,
)
from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader
from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings


@dataclass(frozen=True)
class WorkflowRuntimeWorkerState:
    """描述 workflow runtime worker 返回的当前状态。"""

    observed_state: str
    instance_id: str | None = None
    process_id: int | None = None
    current_run_id: str | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    loaded_snapshot_fingerprint: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowRuntimeWorkerInstance:
    """描述 workflow runtime 当前可观测到的单个 instance 摘要。"""

    instance_id: str
    workflow_runtime_id: str
    state: str
    process_id: int | None = None
    current_run_id: str | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    loaded_snapshot_fingerprint: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowRuntimeWorkerRunResult:
    """描述 workflow runtime worker 返回的一次同步调用结果。"""

    state: str
    outputs: dict[str, object] = field(default_factory=dict)
    template_outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[dict[str, object], ...] = ()
    error_message: str | None = None
    error_details: dict[str, object] = field(default_factory=dict)
    worker_state: WorkflowRuntimeWorkerState = field(
        default_factory=lambda: WorkflowRuntimeWorkerState(observed_state="failed")
    )


@dataclass(frozen=True)
class WorkflowRuntimeAsyncRunCallbacks:
    """描述异步 WorkflowRun 在线程中的状态回写回调。"""

    on_started: Callable[[], None]
    on_completed: Callable[[WorkflowRuntimeWorkerRunResult], None]
    on_cancelled: Callable[[WorkflowRuntimeWorkerState | None], None]
    on_failed: Callable[[ServiceError], None]
    on_timed_out: Callable[[OperationTimeoutError], None]


@dataclass
class _WorkflowRuntimeProcessHandle:
    """描述父进程中维护的单个 runtime worker 句柄。"""

    workflow_runtime_id: str
    process: Any
    request_queue: Any
    response_queue: Any
    lock: Lock = field(default_factory=Lock, repr=False)


@dataclass
class _WorkflowRuntimeAsyncRunHandle:
    """描述父进程中维护的一条异步 WorkflowRun 句柄。"""

    workflow_app_runtime: WorkflowAppRuntime
    workflow_run_id: str
    input_bindings: dict[str, object]
    execution_metadata: dict[str, object]
    timeout_seconds: int
    callbacks: WorkflowRuntimeAsyncRunCallbacks = field(repr=False)
    cancel_event: Event = field(default_factory=Event, repr=False)
    completion_event: Event = field(default_factory=Event, repr=False)
    dispatched_event: Event = field(default_factory=Event, repr=False)
    thread: Thread | None = field(default=None, repr=False)


class WorkflowRuntimeWorkerManager:
    """管理 workflow runtime 的单实例 worker 进程。"""

    def __init__(self, *, settings: BackendServiceSettings) -> None:
        """初始化 workflow runtime worker 管理器。

        参数：
        - settings：backend-service 当前使用的统一配置。
        """

        self.settings = _resolve_backend_service_settings(settings)
        self._context = multiprocessing.get_context("spawn")
        self._handles: dict[str, _WorkflowRuntimeProcessHandle] = {}
        self._async_runs: dict[str, _WorkflowRuntimeAsyncRunHandle] = {}
        self._lock = Lock()
        self._stopping = Event()

    def start(self) -> None:
        """启动管理器本身。

        异步 WorkflowRun 线程按需创建，因此这里只负责清理停止标记。
        """

        self._stopping.clear()

    def stop(self) -> None:
        """停止全部 runtime worker 进程。"""

        with self._lock:
            async_handles = tuple(self._async_runs.values())
            runtime_ids = tuple(self._handles.keys())
        self._stopping.set()
        for async_handle in async_handles:
            async_handle.cancel_event.set()
        for workflow_runtime_id in runtime_ids:
            try:
                self.stop_runtime(workflow_runtime_id)
            except ServiceError:
                continue
        for async_handle in async_handles:
            async_handle.completion_event.wait(timeout=1.0)

    def is_runtime_available(self, workflow_runtime_id: str) -> bool:
        """判断一个 runtime 当前是否仍有活动 worker 进程。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。

        返回：
        - bool：存在活动 worker 进程时返回 True。
        """

        with self._lock:
            handle = self._handles.get(workflow_runtime_id)
        return handle is not None and handle.process.is_alive()

    def start_runtime(self, workflow_app_runtime: WorkflowAppRuntime) -> WorkflowRuntimeWorkerState:
        """拉起一个 runtime 对应的单实例 worker 进程。"""

        with self._lock:
            existing_handle = self._handles.get(workflow_app_runtime.workflow_runtime_id)
            if existing_handle is not None and existing_handle.process.is_alive():
                existing_state = self._request_runtime_state(existing_handle)
                if existing_state.observed_state == "running":
                    return existing_state
                self._cleanup_handle(existing_handle)
                self._handles.pop(workflow_app_runtime.workflow_runtime_id, None)
            if existing_handle is not None:
                self._cleanup_handle(existing_handle)
                self._handles.pop(workflow_app_runtime.workflow_runtime_id, None)

            request_queue = self._context.Queue()
            response_queue = self._context.Queue()
            process = self._context.Process(
                target=run_workflow_runtime_worker_process,
                kwargs={
                    "settings_payload": self.settings.model_dump(mode="python"),
                    "runtime_payload": {
                        "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                        "application_id": workflow_app_runtime.application_id,
                        "application_snapshot_object_key": workflow_app_runtime.application_snapshot_object_key,
                        "template_snapshot_object_key": workflow_app_runtime.template_snapshot_object_key,
                    },
                    "request_queue": request_queue,
                    "response_queue": response_queue,
                },
                name=f"workflow-runtime-{workflow_app_runtime.workflow_runtime_id}",
                daemon=False,
            )
            process.start()
            handle = _WorkflowRuntimeProcessHandle(
                workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
                process=process,
                request_queue=request_queue,
                response_queue=response_queue,
            )
            self._handles[workflow_app_runtime.workflow_runtime_id] = handle

        try:
            return self._wait_for_runtime_state(handle, timeout_seconds=min(workflow_app_runtime.request_timeout_seconds, 15))
        except Exception:
            with self._lock:
                self._handles.pop(workflow_app_runtime.workflow_runtime_id, None)
            self._cleanup_handle(handle)
            raise

    def stop_runtime(self, workflow_runtime_id: str) -> WorkflowRuntimeWorkerState:
        """停止一个 runtime 对应的 worker 进程。"""

        with self._lock:
            handle = self._handles.get(workflow_runtime_id)
        if handle is None:
            return WorkflowRuntimeWorkerState(observed_state="stopped")

        if not handle.process.is_alive():
            with self._lock:
                self._handles.pop(workflow_runtime_id, None)
            self._cleanup_handle(handle)
            return WorkflowRuntimeWorkerState(observed_state="stopped")

        with handle.lock:
            handle.request_queue.put(
                {
                    "message_type": "stop-runtime",
                    "message_id": uuid4().hex,
                    "workflow_runtime_id": workflow_runtime_id,
                }
            )
            runtime_state = self._wait_for_runtime_state(handle, timeout_seconds=10.0)
        with self._lock:
            self._handles.pop(workflow_runtime_id, None)
        self._cleanup_handle(handle)
        return runtime_state

    def get_runtime_health(self, workflow_runtime_id: str) -> WorkflowRuntimeWorkerState:
        """查询一个 runtime 对应 worker 的健康状态。"""

        with self._lock:
            handle = self._handles.get(workflow_runtime_id)
        if handle is None:
            return WorkflowRuntimeWorkerState(observed_state="stopped")
        if not handle.process.is_alive():
            with self._lock:
                self._handles.pop(workflow_runtime_id, None)
            self._cleanup_handle(handle)
            return WorkflowRuntimeWorkerState(
                observed_state="failed",
                last_error="workflow runtime worker 进程已退出",
            )
        return self._request_runtime_state(handle)

    def list_runtime_instances(self, workflow_runtime_id: str) -> tuple[WorkflowRuntimeWorkerInstance, ...]:
        """列出一个 runtime 当前可观测的 instance 摘要。

        参数：
        - workflow_runtime_id：目标 WorkflowAppRuntime id。

        返回：
        - tuple[WorkflowRuntimeWorkerInstance, ...]：当前存活 instance 列表；单实例模型下最多返回 1 条。
        """

        runtime_state = self.get_runtime_health(workflow_runtime_id)
        if runtime_state.instance_id is None:
            return ()
        if runtime_state.observed_state == "stopped":
            return ()
        return (
            WorkflowRuntimeWorkerInstance(
                instance_id=runtime_state.instance_id,
                workflow_runtime_id=workflow_runtime_id,
                state=runtime_state.observed_state,
                process_id=runtime_state.process_id,
                current_run_id=runtime_state.current_run_id,
                started_at=runtime_state.started_at,
                heartbeat_at=runtime_state.heartbeat_at,
                loaded_snapshot_fingerprint=runtime_state.loaded_snapshot_fingerprint,
                last_error=runtime_state.last_error,
                health_summary=dict(runtime_state.health_summary),
            ),
        )

    def submit_async_run(
        self,
        *,
        workflow_app_runtime: WorkflowAppRuntime,
        workflow_run_id: str,
        input_bindings: dict[str, object],
        execution_metadata: dict[str, object],
        timeout_seconds: int,
        callbacks: WorkflowRuntimeAsyncRunCallbacks,
    ) -> None:
        """提交一条异步 WorkflowRun，并在后台线程里串行进入单实例 worker。

        参数：
        - workflow_app_runtime：目标 runtime 的固定快照记录。
        - workflow_run_id：要执行的 WorkflowRun id。
        - input_bindings：本次运行输入。
        - execution_metadata：本次运行元数据。
        - timeout_seconds：本次运行超时秒数。
        - callbacks：后台线程执行过程中的状态回写回调。
        """

        if self._stopping.is_set():
            raise ServiceConfigurationError("workflow runtime worker manager 当前已停止")
        if not self.is_runtime_available(workflow_app_runtime.workflow_runtime_id):
            raise ServiceConfigurationError(
                "workflow runtime worker 当前未运行",
                details={"workflow_runtime_id": workflow_app_runtime.workflow_runtime_id},
            )

        async_handle = _WorkflowRuntimeAsyncRunHandle(
            workflow_app_runtime=workflow_app_runtime,
            workflow_run_id=workflow_run_id,
            input_bindings=dict(input_bindings),
            execution_metadata=dict(execution_metadata),
            timeout_seconds=timeout_seconds,
            callbacks=callbacks,
        )
        async_thread = Thread(
            target=self._run_async_workflow,
            args=(async_handle,),
            name=f"workflow-async-run-{workflow_run_id}",
            daemon=True,
        )
        async_handle.thread = async_thread
        with self._lock:
            self._async_runs[workflow_run_id] = async_handle
        async_thread.start()

    def cancel_async_run(self, workflow_run_id: str, *, timeout_seconds: float = 10.0) -> bool:
        """取消一条已经提交的异步 WorkflowRun。

        参数：
        - workflow_run_id：目标 WorkflowRun id。
        - timeout_seconds：等待取消完成的最大秒数。

        返回：
        - bool：找到异步句柄并在时限内完成取消时返回 True。
        """

        with self._lock:
            async_handle = self._async_runs.get(workflow_run_id)
        if async_handle is None:
            return False
        async_handle.cancel_event.set()
        return async_handle.completion_event.wait(timeout=max(0.1, timeout_seconds))

    def invoke_runtime(
        self,
        *,
        workflow_app_runtime: WorkflowAppRuntime,
        workflow_run_id: str,
        input_bindings: dict[str, object],
        execution_metadata: dict[str, object],
        timeout_seconds: int,
        cancel_event: Event | None = None,
        on_dispatched: Callable[[], None] | None = None,
    ) -> WorkflowRuntimeWorkerRunResult:
        """通过已运行的 worker 发起一次同步调用。"""

        with self._lock:
            handle = self._handles.get(workflow_app_runtime.workflow_runtime_id)
        if handle is None or not handle.process.is_alive():
            raise ServiceConfigurationError(
                "workflow runtime worker 当前未运行",
                details={"workflow_runtime_id": workflow_app_runtime.workflow_runtime_id},
            )

        lock_acquired = False
        while not lock_acquired:
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelledError(
                    "workflow run 已取消",
                    details={
                        "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                        "workflow_run_id": workflow_run_id,
                    },
                )
            if not handle.process.is_alive():
                self._terminate_failed_handle(
                    workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
                    handle=handle,
                )
                raise ServiceConfigurationError(
                    "workflow runtime worker 当前未运行",
                    details={"workflow_runtime_id": workflow_app_runtime.workflow_runtime_id},
                )
            lock_acquired = handle.lock.acquire(timeout=0.1)

        try:
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelledError(
                    "workflow run 已取消",
                    details={
                        "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                        "workflow_run_id": workflow_run_id,
                    },
                )
            handle.request_queue.put(
                {
                    "message_type": "invoke-run",
                    "message_id": uuid4().hex,
                    "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                    "workflow_run_id": workflow_run_id,
                    "requested_timeout_seconds": timeout_seconds,
                    "input_bindings": dict(input_bindings),
                    "execution_metadata": dict(execution_metadata),
                }
            )
            if on_dispatched is not None:
                on_dispatched()

            deadline = monotonic() + float(timeout_seconds)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._terminate_failed_handle(
                        workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
                        handle=handle,
                    )
                    raise OperationCancelledError(
                        "workflow run 已取消",
                        details={
                            "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                            "workflow_run_id": workflow_run_id,
                        },
                    )
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    self._terminate_failed_handle(
                        workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
                        handle=handle,
                    )
                    raise OperationTimeoutError(
                        "等待 workflow runtime worker 同步调用结果超时",
                        details={
                            "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                            "workflow_run_id": workflow_run_id,
                            "timeout_seconds": timeout_seconds,
                        },
                    )
                try:
                    message = handle.response_queue.get(timeout=max(0.1, min(0.2, remaining_seconds)))
                    break
                except Empty:
                    if not handle.process.is_alive():
                        self._terminate_failed_handle(
                            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
                            handle=handle,
                        )
                        raise ServiceConfigurationError(
                            "workflow runtime worker 进程已退出",
                            details={
                                "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                                "workflow_run_id": workflow_run_id,
                            },
                        )
                    continue
        finally:
            if lock_acquired:
                try:
                    handle.lock.release()
                except RuntimeError:
                    pass

        return _deserialize_run_result(message)

    def _run_async_workflow(self, async_handle: _WorkflowRuntimeAsyncRunHandle) -> None:
        """在后台线程里执行一条异步 WorkflowRun。"""

        try:
            worker_result = self.invoke_runtime(
                workflow_app_runtime=async_handle.workflow_app_runtime,
                workflow_run_id=async_handle.workflow_run_id,
                input_bindings=async_handle.input_bindings,
                execution_metadata=async_handle.execution_metadata,
                timeout_seconds=async_handle.timeout_seconds,
                cancel_event=async_handle.cancel_event,
                on_dispatched=lambda: self._mark_async_run_dispatched(async_handle),
            )
            async_handle.callbacks.on_completed(worker_result)
        except OperationCancelledError:
            runtime_state: WorkflowRuntimeWorkerState | None = None
            if async_handle.dispatched_event.is_set() and not self._stopping.is_set():
                try:
                    runtime_state = self.start_runtime(async_handle.workflow_app_runtime)
                except ServiceError as error:
                    runtime_state = WorkflowRuntimeWorkerState(
                        observed_state="failed",
                        last_error=error.message,
                        health_summary={
                            "mode": "single-instance-sync",
                            "worker_state": "failed",
                            "last_error": error.message,
                        },
                    )
            async_handle.callbacks.on_cancelled(runtime_state)
        except OperationTimeoutError as error:
            async_handle.callbacks.on_timed_out(error)
        except ServiceError as error:
            async_handle.callbacks.on_failed(error)
        finally:
            async_handle.completion_event.set()
            with self._lock:
                self._async_runs.pop(async_handle.workflow_run_id, None)

    @staticmethod
    def _mark_async_run_dispatched(async_handle: _WorkflowRuntimeAsyncRunHandle) -> None:
        """标记一条异步 WorkflowRun 已进入 worker 执行。"""

        if async_handle.dispatched_event.is_set():
            return
        async_handle.dispatched_event.set()
        async_handle.callbacks.on_started()

    def _request_runtime_state(self, handle: _WorkflowRuntimeProcessHandle) -> WorkflowRuntimeWorkerState:
        """向指定 worker 请求当前状态。"""

        with handle.lock:
            handle.request_queue.put(
                {
                    "message_type": "health-check",
                    "message_id": uuid4().hex,
                    "workflow_runtime_id": handle.workflow_runtime_id,
                }
            )
            return self._wait_for_runtime_state(handle, timeout_seconds=5.0)

    def _wait_for_runtime_state(
        self,
        handle: _WorkflowRuntimeProcessHandle,
        *,
        timeout_seconds: float,
    ) -> WorkflowRuntimeWorkerState:
        """等待 worker 返回 runtime-state 消息。"""

        try:
            message = handle.response_queue.get(timeout=max(0.1, timeout_seconds))
        except Empty as exc:
            raise OperationTimeoutError(
                "等待 workflow runtime worker 状态响应超时",
                details={
                    "workflow_runtime_id": handle.workflow_runtime_id,
                    "timeout_seconds": timeout_seconds,
                },
            ) from exc
        return _deserialize_runtime_state(message)

    def _terminate_failed_handle(
        self,
        *,
        workflow_runtime_id: str,
        handle: _WorkflowRuntimeProcessHandle,
    ) -> None:
        """在同步调用超时或崩溃后强制清理句柄。"""

        with self._lock:
            self._handles.pop(workflow_runtime_id, None)
        self._cleanup_handle(handle)

    def _cleanup_handle(self, handle: _WorkflowRuntimeProcessHandle) -> None:
        """关闭并回收一个 worker 句柄。"""

        if handle.process.is_alive():
            handle.process.terminate()
            handle.process.join(timeout=1.0)
        handle.request_queue.close()
        handle.request_queue.join_thread()
        handle.response_queue.close()
        handle.response_queue.join_thread()


def run_workflow_runtime_worker_process(
    *,
    settings_payload: dict[str, object],
    runtime_payload: dict[str, object],
    request_queue: Queue[Any],
    response_queue: Queue[Any],
) -> None:
    """workflow runtime worker 子进程入口。"""

    session_factory: SessionFactory | None = None
    sync_supervisor: YoloXDeploymentProcessSupervisor | None = None
    async_supervisor: YoloXDeploymentProcessSupervisor | None = None
    try:
        settings = BackendServiceSettings.model_validate(settings_payload)
        session_factory = SessionFactory(settings.to_database_settings())
        dataset_storage = LocalDatasetStorage(settings.to_dataset_storage_settings())
        queue_backend = LocalFileQueueBackend(settings.to_queue_settings())
        node_pack_loader = LocalNodePackLoader(settings.custom_nodes.root_dir)
        node_pack_loader.refresh()
        node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
        runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
            node_catalog_registry=node_catalog_registry,
            node_pack_loader=node_pack_loader,
        )
        runtime_registry_loader.refresh()
        sync_supervisor = YoloXDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="sync",
            settings=settings.deployment_process_supervisor,
        )
        async_supervisor = YoloXDeploymentProcessSupervisor(
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            runtime_mode="async",
            settings=settings.deployment_process_supervisor,
        )
        sync_supervisor.start()
        async_supervisor.start()
        runtime_context = WorkflowServiceNodeRuntimeContext(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            yolox_sync_deployment_process_supervisor=sync_supervisor,
            yolox_async_deployment_process_supervisor=async_supervisor,
        )
        workflow_runtime_id = _require_payload_str(runtime_payload, "workflow_runtime_id")
        application_id = _require_payload_str(runtime_payload, "application_id")
        application_snapshot_object_key = _require_payload_str(runtime_payload, "application_snapshot_object_key")
        template_snapshot_object_key = _require_payload_str(runtime_payload, "template_snapshot_object_key")
        snapshot_fingerprint = build_snapshot_fingerprint(
            dataset_storage=dataset_storage,
            application_snapshot_object_key=application_snapshot_object_key,
            template_snapshot_object_key=template_snapshot_object_key,
        )
        snapshot_execution_service = SnapshotExecutionService(
            dataset_storage=dataset_storage,
            node_catalog_registry=node_catalog_registry,
            runtime_registry=runtime_registry_loader.get_runtime_registry(),
            runtime_context=runtime_context,
        )
        worker_started_at = _now_isoformat()
        runtime_instance_id = _build_runtime_instance_id(workflow_runtime_id)
        current_observed_state = "running"
        current_last_error: str | None = None
        current_run_id: str | None = None
        response_queue.put(
            _build_runtime_state_message(
                workflow_runtime_id=workflow_runtime_id,
                observed_state=current_observed_state,
                instance_id=runtime_instance_id,
                process_id=multiprocessing.current_process().pid,
                current_run_id=current_run_id,
                started_at=worker_started_at,
                heartbeat_at=_now_isoformat(),
                loaded_snapshot_fingerprint=snapshot_fingerprint,
                last_error=current_last_error,
            )
        )
        while True:
            command = request_queue.get()
            message_type = _read_message_type(command)
            if message_type == "health-check":
                response_queue.put(
                    _build_runtime_state_message(
                        workflow_runtime_id=workflow_runtime_id,
                        observed_state=current_observed_state,
                        instance_id=runtime_instance_id,
                        process_id=multiprocessing.current_process().pid,
                        current_run_id=current_run_id,
                        started_at=worker_started_at,
                        heartbeat_at=_now_isoformat(),
                        loaded_snapshot_fingerprint=snapshot_fingerprint,
                        last_error=current_last_error,
                    )
                )
                continue
            if message_type == "stop-runtime":
                current_observed_state = "stopped"
                response_queue.put(
                    _build_runtime_state_message(
                        workflow_runtime_id=workflow_runtime_id,
                        observed_state=current_observed_state,
                        instance_id=runtime_instance_id,
                        process_id=multiprocessing.current_process().pid,
                        current_run_id=None,
                        started_at=worker_started_at,
                        heartbeat_at=_now_isoformat(),
                        loaded_snapshot_fingerprint=snapshot_fingerprint,
                        last_error=current_last_error,
                    )
                )
                break
            if message_type != "invoke-run":
                response_queue.put(
                    _build_worker_error_message(
                        workflow_runtime_id=workflow_runtime_id,
                        workflow_run_id=None,
                        error_message="workflow runtime worker 收到未支持的消息类型",
                        error_details={"message_type": message_type},
                        state="failed",
                        instance_id=runtime_instance_id,
                        current_run_id=current_run_id,
                        started_at=worker_started_at,
                        loaded_snapshot_fingerprint=snapshot_fingerprint,
                    )
                )
                continue

            workflow_run_id = _require_payload_str(command, "workflow_run_id")
            requested_timeout_seconds = _read_timeout_seconds(command)
            input_bindings = _require_payload_dict(command, "input_bindings")
            execution_metadata = _require_payload_dict(command, "execution_metadata")
            execution_metadata.setdefault("workflow_run_id", workflow_run_id)
            current_run_id = workflow_run_id
            try:
                execution_result = snapshot_execution_service.execute(
                    WorkflowSnapshotExecutionRequest(
                        project_id=_read_project_id_from_snapshot(
                            dataset_storage=dataset_storage,
                            application_snapshot_object_key=application_snapshot_object_key,
                        ),
                        application_id=application_id,
                        application_snapshot_object_key=application_snapshot_object_key,
                        template_snapshot_object_key=template_snapshot_object_key,
                        input_bindings=input_bindings,
                        execution_metadata=execution_metadata,
                    )
                )
                current_observed_state = "running"
                current_last_error = None
                response_queue.put(
                    {
                        "message_type": "run-result",
                        "workflow_runtime_id": workflow_runtime_id,
                        "workflow_run_id": workflow_run_id,
                        "state": "succeeded",
                        "outputs": dict(execution_result.outputs),
                        "template_outputs": dict(execution_result.template_outputs),
                        "node_records": [dict(item) for item in _serialize_node_records(execution_result.node_records)],
                        "error_message": None,
                        "worker_state": {
                            "observed_state": current_observed_state,
                            "instance_id": runtime_instance_id,
                            "process_id": multiprocessing.current_process().pid,
                            "current_run_id": None,
                            "started_at": worker_started_at,
                            "heartbeat_at": _now_isoformat(),
                            "loaded_snapshot_fingerprint": snapshot_fingerprint,
                            "last_error": current_last_error,
                            "health_summary": {
                                "mode": "single-instance-sync",
                                "last_requested_timeout_seconds": requested_timeout_seconds,
                            },
                        },
                    }
                )
            except ServiceError as exc:
                current_observed_state = "failed"
                current_last_error = exc.message
                response_queue.put(
                    _build_worker_error_message(
                        workflow_runtime_id=workflow_runtime_id,
                        workflow_run_id=workflow_run_id,
                        error_message=exc.message,
                        error_details={
                            "error_code": exc.code,
                            **dict(exc.details),
                        },
                        state="failed",
                        instance_id=runtime_instance_id,
                        current_run_id=None,
                        started_at=worker_started_at,
                        loaded_snapshot_fingerprint=snapshot_fingerprint,
                    )
                )
            except Exception as exc:  # pragma: no cover - 子进程兜底错误封装
                current_observed_state = "failed"
                current_last_error = "workflow runtime worker 执行失败"
                response_queue.put(
                    _build_worker_error_message(
                        workflow_runtime_id=workflow_runtime_id,
                        workflow_run_id=workflow_run_id,
                        error_message="workflow runtime worker 执行失败",
                        error_details={
                            "error_type": type(exc).__name__,
                            "error_message": str(exc) or type(exc).__name__,
                        },
                        state="failed",
                        instance_id=runtime_instance_id,
                        current_run_id=None,
                        started_at=worker_started_at,
                        loaded_snapshot_fingerprint=snapshot_fingerprint,
                    )
                )
            finally:
                current_run_id = None
    finally:
        if sync_supervisor is not None:
            sync_supervisor.stop()
        if async_supervisor is not None:
            async_supervisor.stop()
        if session_factory is not None:
            session_factory.engine.dispose()


def _build_runtime_state_message(
    *,
    workflow_runtime_id: str,
    observed_state: str,
    instance_id: str | None,
    process_id: int | None,
    current_run_id: str | None,
    started_at: str | None,
    heartbeat_at: str,
    loaded_snapshot_fingerprint: str | None,
    last_error: str | None = None,
) -> dict[str, object]:
    """构造 runtime-state 消息。"""

    return {
        "message_type": "runtime-state",
        "workflow_runtime_id": workflow_runtime_id,
        "observed_state": observed_state,
        "instance_id": instance_id,
        "process_id": process_id,
        "current_run_id": current_run_id,
        "started_at": started_at,
        "heartbeat_at": heartbeat_at,
        "loaded_snapshot_fingerprint": loaded_snapshot_fingerprint,
        "last_error": last_error,
        "health_summary": {"mode": "single-instance-sync"},
    }


def _build_worker_error_message(
    *,
    workflow_runtime_id: str,
    workflow_run_id: str | None,
    error_message: str,
    error_details: dict[str, object],
    state: str,
    instance_id: str | None,
    current_run_id: str | None,
    started_at: str | None,
    loaded_snapshot_fingerprint: str | None,
) -> dict[str, object]:
    """构造 worker-error 消息。"""

    return {
        "message_type": "worker-error",
        "workflow_runtime_id": workflow_runtime_id,
        "workflow_run_id": workflow_run_id,
        "state": state,
        "error_message": error_message,
        "error_details": dict(error_details),
        "worker_state": {
            "observed_state": "failed",
            "instance_id": instance_id,
            "process_id": multiprocessing.current_process().pid,
            "current_run_id": current_run_id,
            "started_at": started_at,
            "heartbeat_at": _now_isoformat(),
            "loaded_snapshot_fingerprint": loaded_snapshot_fingerprint,
            "last_error": error_message,
            "health_summary": {"mode": "single-instance-sync"},
        },
    }


def _deserialize_runtime_state(message: object) -> WorkflowRuntimeWorkerState:
    """把 runtime-state 消息反序列化为父进程可用对象。"""

    if not isinstance(message, dict) or message.get("message_type") != "runtime-state":
        raise ServiceConfigurationError("workflow runtime worker 返回了无效状态消息")
    return WorkflowRuntimeWorkerState(
        observed_state=_require_payload_str(message, "observed_state"),
        instance_id=_read_optional_str(message, "instance_id"),
        process_id=_read_optional_int(message, "process_id"),
        current_run_id=_read_optional_str(message, "current_run_id"),
        started_at=_read_optional_str(message, "started_at"),
        heartbeat_at=_read_optional_str(message, "heartbeat_at"),
        loaded_snapshot_fingerprint=_read_optional_str(message, "loaded_snapshot_fingerprint"),
        last_error=_read_optional_str(message, "last_error"),
        health_summary=_require_payload_dict(message, "health_summary"),
    )


def _deserialize_run_result(message: object) -> WorkflowRuntimeWorkerRunResult:
    """把 worker run 结果反序列化为父进程可用对象。"""

    if not isinstance(message, dict):
        raise ServiceConfigurationError("workflow runtime worker 返回了无效执行消息")
    message_type = str(message.get("message_type") or "")
    if message_type not in {"run-result", "worker-error"}:
        raise ServiceConfigurationError(
            "workflow runtime worker 返回了未支持的执行消息类型",
            details={"message_type": message_type},
        )
    worker_state_payload = message.get("worker_state") if isinstance(message.get("worker_state"), dict) else {}
    worker_state = WorkflowRuntimeWorkerState(
        observed_state=str(worker_state_payload.get("observed_state") or "failed"),
        instance_id=_read_optional_str(worker_state_payload, "instance_id"),
        process_id=_read_optional_int(worker_state_payload, "process_id"),
        current_run_id=_read_optional_str(worker_state_payload, "current_run_id"),
        started_at=_read_optional_str(worker_state_payload, "started_at"),
        heartbeat_at=_read_optional_str(worker_state_payload, "heartbeat_at"),
        loaded_snapshot_fingerprint=_read_optional_str(worker_state_payload, "loaded_snapshot_fingerprint"),
        last_error=_read_optional_str(worker_state_payload, "last_error"),
        health_summary=_require_payload_dict(worker_state_payload, "health_summary"),
    )
    return WorkflowRuntimeWorkerRunResult(
        state=str(message.get("state") or "failed"),
        outputs=_require_payload_dict(message, "outputs"),
        template_outputs=_require_payload_dict(message, "template_outputs"),
        node_records=tuple(dict(item) for item in (message.get("node_records") or []) if isinstance(item, dict)),
        error_message=_read_optional_str(message, "error_message"),
        error_details=_require_payload_dict(message, "error_details"),
        worker_state=worker_state,
    )


def _serialize_node_records(node_records: tuple[dict[str, object], ...] | tuple[Any, ...]) -> tuple[dict[str, object], ...]:
    """把节点执行记录统一转换为 JSON 可序列化字典。"""

    serialized: list[dict[str, object]] = []
    for item in node_records:
        if isinstance(item, dict):
            serialized.append(dict(item))
            continue
        serialized.append(
            {
                "node_id": getattr(item, "node_id", ""),
                "node_type_id": getattr(item, "node_type_id", ""),
                "runtime_kind": getattr(item, "runtime_kind", ""),
                "outputs": dict(getattr(item, "outputs", {}) or {}),
            }
        )
    return tuple(serialized)


def _read_message_type(payload: object) -> str:
    """读取命令消息类型。"""

    return _require_payload_str(payload, "message_type")


def _read_timeout_seconds(payload: object) -> int:
    """读取命令里的超时秒数。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow runtime worker 命令负载格式无效")
    value = payload.get("requested_timeout_seconds")
    if isinstance(value, int) and value > 0:
        return value
    return 60


def _read_project_id_from_snapshot(
    *,
    dataset_storage: LocalDatasetStorage,
    application_snapshot_object_key: str,
) -> str:
    """从 application snapshot 中读取 project_id。"""

    payload = dataset_storage.read_json(application_snapshot_object_key)
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    if isinstance(metadata, dict):
        project_id = metadata.get("project_id")
        if isinstance(project_id, str) and project_id.strip():
            return project_id.strip()
    raise ServiceConfigurationError("workflow runtime application snapshot 缺少 project_id metadata")


def _require_payload_str(payload: object, field_name: str) -> str:
    """从字典负载中读取必填字符串字段。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow runtime worker 负载格式无效")
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ServiceConfigurationError(
            "workflow runtime worker 负载缺少有效字符串字段",
            details={"field_name": field_name},
        )
    return value.strip()


def _require_payload_dict(payload: object, field_name: str) -> dict[str, object]:
    """从字典负载中读取对象字段。"""

    if not isinstance(payload, dict):
        raise ServiceConfigurationError("workflow runtime worker 负载格式无效")
    value = payload.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ServiceConfigurationError(
            "workflow runtime worker 负载缺少有效对象字段",
            details={"field_name": field_name},
        )
    return {str(key): item for key, item in value.items()}


def _read_optional_str(payload: object, field_name: str) -> str | None:
    """从字典负载中读取可选字符串字段。"""

    if not isinstance(payload, dict):
        return None
    value = payload.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_optional_int(payload: object, field_name: str) -> int | None:
    """从字典负载中读取可选整数字段。"""

    if not isinstance(payload, dict):
        return None
    value = payload.get(field_name)
    if isinstance(value, int):
        return value
    return None


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_runtime_instance_id(workflow_runtime_id: str) -> str:
    """构造单实例 runtime 使用的稳定 instance_id。"""

    return f"{workflow_runtime_id}-primary"


def _resolve_backend_service_settings(settings: BackendServiceSettings) -> BackendServiceSettings:
    """把 backend-service settings 规范化为适合子进程复用的绝对路径版本。"""

    normalized_settings = BackendServiceSettings.model_validate(settings.model_dump(mode="python"))
    normalized_settings.database.url = _resolve_database_url(normalized_settings.database.url)
    normalized_settings.dataset_storage.root_dir = str(Path(normalized_settings.dataset_storage.root_dir).resolve())
    normalized_settings.queue.root_dir = str(Path(normalized_settings.queue.root_dir).resolve())
    normalized_settings.custom_nodes.root_dir = str(Path(normalized_settings.custom_nodes.root_dir).resolve())
    return normalized_settings


def _resolve_database_url(database_url: str) -> str:
    """把 SQLite 文件数据库 URL 规范化为绝对路径。"""

    parsed_url: URL = make_url(database_url)
    if parsed_url.drivername != "sqlite" or parsed_url.database in (None, ":memory:"):
        return database_url
    resolved_database_path = Path(parsed_url.database).resolve()
    return parsed_url.set(database=resolved_database_path.as_posix()).render_as_string(
        hide_password=False
    )