"""workflow runtime worker 管理器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from queue import Empty
from threading import Event, Lock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import uuid4
import logging
import multiprocessing

from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.local_buffers import (
    LocalBufferBrokerClient,
    LocalBufferBrokerEventChannel,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
    WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY,
    build_process_safe_execution_metadata,
    list_registered_execution_cleanups,
)
from backend.service.application.workflows.runtime_app_events import append_workflow_app_runtime_event
from backend.service.application.workflows.worker.health import (
    WorkflowRuntimeWorkerInstance,
    WorkflowRuntimeWorkerState,
    build_parent_broker_channel_summary,
    build_synthetic_runtime_state,
    deserialize_runtime_state,
    now_isoformat,
    try_deserialize_runtime_state_message,
)
from backend.service.application.workflows.worker.messages import (
    WorkflowRuntimeAsyncRunCallbacks,
    WorkflowRuntimePendingResponse as _WorkflowRuntimePendingResponse,
    WorkflowRuntimeWorkerRunResult,
    deserialize_run_result,
    resolve_backend_service_settings,
    try_deserialize_run_result_worker_state,
)
from backend.service.application.workflows.worker import process as worker_process
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings

if TYPE_CHECKING:
    from backend.service.application.deployments import (
        PublishedInferenceGateway,
        PublishedInferenceGatewayDispatcher,
        PublishedInferenceGatewayEventChannel,
    )


LOGGER = logging.getLogger(__name__)


@dataclass
class _WorkflowRuntimeProcessHandle:
    """描述父进程中维护的单个 runtime worker 句柄。"""

    workflow_runtime_id: str
    process: Any
    request_queue: Any
    response_queue: Any
    local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None
    published_inference_gateway_channel: PublishedInferenceGatewayEventChannel | None = None
    published_inference_gateway_dispatcher: PublishedInferenceGatewayDispatcher | None = None
    heartbeat_interval_seconds: int = 5
    heartbeat_timeout_seconds: int = 15
    response_thread: Thread | None = None
    response_stop_event: Event = field(default_factory=Event, repr=False)
    pending_responses: dict[str, _WorkflowRuntimePendingResponse] = field(default_factory=dict, repr=False)
    started_event: Event = field(default_factory=Event, repr=False)
    request_lock: Lock = field(default_factory=Lock, repr=False)
    state_lock: Lock = field(default_factory=Lock, repr=False)
    latest_runtime_state: WorkflowRuntimeWorkerState | None = None
    latest_runtime_state_monotonic: float | None = None
    expected_shutdown: bool = False
    heartbeat_timeout_reported: bool = False
    background_failure_reported: bool = False


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

    def __init__(
        self,
        *,
        settings: BackendServiceSettings,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        local_buffer_broker_event_channel_provider: Callable[[], LocalBufferBrokerEventChannel | None] | None = None,
        published_inference_gateway: PublishedInferenceGateway | None = None,
    ) -> None:
        """初始化 workflow runtime worker 管理器。

        参数：
        - settings：backend-service 当前使用的统一配置。
        - session_factory：数据库会话工厂；用于后台 heartbeat 状态回写。
        - dataset_storage：本地文件存储；用于后台事件写入。
        - local_buffer_broker_event_channel_provider：启动 worker 子进程时读取 broker 事件通道的函数。
        - published_inference_gateway：父进程持有的已发布推理 gateway。
        """

        self.settings = resolve_backend_service_settings(settings)
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.service_event_bus = session_factory.service_event_bus
        self.local_buffer_broker_event_channel_provider = local_buffer_broker_event_channel_provider
        self.published_inference_gateway = published_inference_gateway
        self._context = multiprocessing.get_context("spawn")
        self._handles: dict[str, _WorkflowRuntimeProcessHandle] = {}
        self._async_runs: dict[str, _WorkflowRuntimeAsyncRunHandle] = {}
        self._lock = Lock()
        self._stopping = Event()
        self._monitor_stop_event = Event()
        self._monitor_thread: Thread | None = None
        self._cleanup_client_lock = Lock()
        self._cleanup_local_buffer_client: LocalBufferBrokerClient | None = None

    def start(self) -> None:
        """启动管理器本身。

        异步 WorkflowRun 线程按需创建，因此这里只负责清理停止标记。
        """

        self._stopping.clear()
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_stop_event.clear()
            self._monitor_thread = Thread(
                target=self._run_monitor_loop,
                name="workflow-runtime-worker-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def stop(self) -> None:
        """停止全部 runtime worker 进程。"""

        with self._lock:
            async_handles = tuple(self._async_runs.values())
            runtime_ids = tuple(self._handles.keys())
        self._stopping.set()
        self._monitor_stop_event.set()
        monitor_thread = self._monitor_thread
        if monitor_thread is not None:
            monitor_thread.join(timeout=1.0)
            if not monitor_thread.is_alive():
                self._monitor_thread = None
        for async_handle in async_handles:
            async_handle.cancel_event.set()
        for workflow_runtime_id in runtime_ids:
            try:
                self.stop_runtime(workflow_runtime_id)
            except ServiceError:
                continue
        for async_handle in async_handles:
            async_handle.completion_event.wait(timeout=1.0)
        self._close_cleanup_local_buffer_client()

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
                existing_state = self._read_cached_runtime_state(existing_handle) or self._request_runtime_state(existing_handle)
                if existing_state.observed_state == "running":
                    return existing_state
                self._cleanup_handle(existing_handle)
                self._handles.pop(workflow_app_runtime.workflow_runtime_id, None)
            elif existing_handle is not None:
                self._cleanup_handle(existing_handle)
                self._handles.pop(workflow_app_runtime.workflow_runtime_id, None)

            request_queue = self._context.Queue()
            response_queue = self._context.Queue()
            local_buffer_broker_event_channel = self._resolve_local_buffer_broker_event_channel()
            gateway_channel = self._build_published_inference_gateway_channel()
            gateway_dispatcher = self._build_published_inference_gateway_dispatcher(gateway_channel)
            if gateway_dispatcher is not None:
                gateway_dispatcher.start()
            process = self._context.Process(
                target=worker_process.run_workflow_runtime_worker_process,
                kwargs={
                    "settings_payload": self.settings.model_dump(mode="python"),
                    "runtime_payload": {
                        "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                        "application_id": workflow_app_runtime.application_id,
                        "application_snapshot_object_key": workflow_app_runtime.application_snapshot_object_key,
                        "template_snapshot_object_key": workflow_app_runtime.template_snapshot_object_key,
                        "heartbeat_interval_seconds": workflow_app_runtime.heartbeat_interval_seconds,
                    },
                    "local_buffer_broker_event_channel": local_buffer_broker_event_channel,
                    "published_inference_gateway_event_channel": gateway_channel,
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
                local_buffer_broker_event_channel=local_buffer_broker_event_channel,
                published_inference_gateway_channel=gateway_channel,
                published_inference_gateway_dispatcher=gateway_dispatcher,
                heartbeat_interval_seconds=workflow_app_runtime.heartbeat_interval_seconds,
                heartbeat_timeout_seconds=workflow_app_runtime.heartbeat_timeout_seconds,
            )
            handle.response_thread = Thread(
                target=self._run_response_loop,
                args=(handle,),
                name=f"workflow-runtime-response-{workflow_app_runtime.workflow_runtime_id}",
                daemon=True,
            )
            handle.response_thread.start()
            self._handles[workflow_app_runtime.workflow_runtime_id] = handle

        try:
            return self._wait_for_startup_state(
                handle,
                timeout_seconds=self._resolve_runtime_start_timeout_seconds(),
            )
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

        with handle.state_lock:
            handle.expected_shutdown = True
        with handle.request_lock:
            message_id = uuid4().hex
            runtime_state = self._wait_for_runtime_state(
                handle,
                message_id=message_id,
                timeout_seconds=10.0,
                payload={
                    "message_type": "stop-runtime",
                    "message_id": message_id,
                    "workflow_runtime_id": workflow_runtime_id,
                },
            )
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
        cached_state = self._read_cached_runtime_state(handle)
        if cached_state is not None:
            return cached_state
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
            self.cleanup_parent_local_buffer_leases(execution_metadata)
            raise ServiceConfigurationError("workflow runtime worker manager 当前已停止")
        if not self.is_runtime_available(workflow_app_runtime.workflow_runtime_id):
            self.cleanup_parent_local_buffer_leases(execution_metadata)
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
        try:
            async_thread.start()
        except Exception as exc:
            with self._lock:
                self._async_runs.pop(workflow_run_id, None)
            self.cleanup_parent_local_buffer_leases(execution_metadata)
            raise ServiceConfigurationError(
                "workflow run 后台线程启动失败",
                details={
                    "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                    "workflow_run_id": workflow_run_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc) or type(exc).__name__,
                },
            ) from exc

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

        invoke_started_at = monotonic()
        with self._lock:
            handle = self._handles.get(workflow_app_runtime.workflow_runtime_id)
        if handle is None or not handle.process.is_alive():
            raise ServiceConfigurationError(
                "workflow runtime worker 当前未运行",
                details={"workflow_runtime_id": workflow_app_runtime.workflow_runtime_id},
            )

        lock_acquired = False
        lock_wait_started_at = monotonic()
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
            lock_acquired = handle.request_lock.acquire(timeout=0.1)
        request_lock_wait_ms = _elapsed_ms(lock_wait_started_at)

        try:
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelledError(
                    "workflow run 已取消",
                    details={
                        "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                        "workflow_run_id": workflow_run_id,
                    },
                )
            message_id = uuid4().hex
            pending = _WorkflowRuntimePendingResponse()
            process_metadata_source = dict(execution_metadata)
            process_metadata_source[WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY] = float(
                timeout_seconds
            )
            process_execution_metadata = build_process_safe_execution_metadata(
                process_metadata_source
            )
            with handle.state_lock:
                if not handle.process.is_alive():
                    self._terminate_failed_handle(
                        workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
                        handle=handle,
                    )
                    raise ServiceConfigurationError(
                        "workflow runtime worker 当前未运行",
                        details={"workflow_runtime_id": workflow_app_runtime.workflow_runtime_id},
                    )
                handle.pending_responses[message_id] = pending
                queue_put_started_at = monotonic()
                handle.request_queue.put(
                    {
                        "message_type": "invoke-run",
                        "message_id": message_id,
                        "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                        "workflow_run_id": workflow_run_id,
                        "requested_timeout_seconds": timeout_seconds,
                        "input_bindings": dict(input_bindings),
                        "execution_metadata": process_execution_metadata,
                    }
                )
                request_queue_put_ms = _elapsed_ms(queue_put_started_at)
            if on_dispatched is not None:
                on_dispatched()

            deadline = monotonic() + float(timeout_seconds)
            reply_wait_started_at = monotonic()
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
                if pending.event.wait(timeout=max(0.1, min(0.2, remaining_seconds))):
                    message = pending.response or {}
                    worker_response_received = True
                    worker_reply_wait_ms = _elapsed_ms(reply_wait_started_at)
                    break
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
        finally:
            if lock_acquired:
                try:
                    handle.request_lock.release()
                except RuntimeError:
                    pass
            with handle.state_lock:
                handle.pending_responses.pop(message_id if 'message_id' in locals() else "", None)
            if "message_id" in locals():
                self.cleanup_workflow_run_local_buffer_owner(workflow_run_id)
            if not locals().get("worker_response_received", False):
                # worker 未返回时无法确认其 finally 是否运行；覆盖入队失败、取消、
                # 超时和进程硬退出，释放 TriggerSource 输入等父进程已知 lease。
                self.cleanup_parent_local_buffer_leases(execution_metadata)

        worker_result = deserialize_run_result(message)
        timings = dict(worker_result.timings)
        timings.update(
            {
                "worker_request_lock_wait_ms": request_lock_wait_ms,
                "worker_request_queue_put_ms": request_queue_put_ms if "request_queue_put_ms" in locals() else None,
                "worker_reply_wait_ms": worker_reply_wait_ms if "worker_reply_wait_ms" in locals() else None,
                "worker_manager_invoke_total_ms": _elapsed_ms(invoke_started_at),
                "worker_runtime_mode": "single-instance-sync",
            }
        )
        return replace(worker_result, timings=timings)

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
            self.cleanup_parent_local_buffer_leases(async_handle.execution_metadata)
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
            self.cleanup_parent_local_buffer_leases(async_handle.execution_metadata)
            async_handle.callbacks.on_timed_out(error)
        except ServiceError as error:
            self.cleanup_parent_local_buffer_leases(async_handle.execution_metadata)
            async_handle.callbacks.on_failed(error)
        except Exception as exc:
            self.cleanup_parent_local_buffer_leases(async_handle.execution_metadata)
            async_handle.callbacks.on_failed(
                ServiceConfigurationError(
                    "workflow runtime worker 调用异常退出",
                    details={
                        "workflow_runtime_id": async_handle.workflow_app_runtime.workflow_runtime_id,
                        "workflow_run_id": async_handle.workflow_run_id,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc) or type(exc).__name__,
                    },
                )
            )
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

    def cleanup_parent_local_buffer_leases(
        self,
        execution_metadata: dict[str, object],
    ) -> int:
        """父进程兜底释放 worker 未能执行 cleanup 的 LocalBufferBroker lease。"""

        cleanup_items = tuple(
            item
            for item in list_registered_execution_cleanups(execution_metadata)
            if item.resource_kind == WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE
        )
        if not cleanup_items:
            return 0
        try:
            client = self._get_cleanup_local_buffer_client()
        except Exception as exc:
            LOGGER.warning("创建 LocalBufferBroker cleanup client 失败: %s", exc)
            return 0
        if client is None:
            return 0
        released_count = 0
        for cleanup_item in cleanup_items:
            pool_name_value = cleanup_item.metadata.get("pool_name")
            try:
                client.release(
                    cleanup_item.resource_id,
                    pool_name=pool_name_value if isinstance(pool_name_value, str) else None,
                )
                released_count += 1
            except InvalidRequestError:
                # worker 可能已在退出前完成 cleanup；release 保持幂等兜底语义。
                continue
            except Exception as exc:
                LOGGER.warning(
                    "父进程释放 LocalBufferBroker lease 失败: lease_id=%s error=%s",
                    cleanup_item.resource_id,
                    exc,
                )
                self._invalidate_cleanup_local_buffer_client(client)
                break
        return released_count

    def cleanup_workflow_run_local_buffer_owner(self, workflow_run_id: str) -> int:
        """按 run owner 前缀释放 worker 可能未登记的临时 ROI lease。"""

        normalized_run_id = workflow_run_id.strip()
        if not normalized_run_id:
            return 0
        try:
            client = self._get_cleanup_local_buffer_client()
        except Exception as exc:
            LOGGER.warning("创建 LocalBufferBroker owner cleanup client 失败: %s", exc)
            return 0
        if client is None:
            return 0
        try:
            return client.release_owner(
                owner_kind="workflow-runtime",
                owner_id_prefix=f"{normalized_run_id}:",
            )
        except Exception as exc:
            LOGGER.warning(
                "父进程按 Workflow Run owner 释放 LocalBufferBroker lease 失败: "
                "workflow_run_id=%s error=%s",
                normalized_run_id,
                exc,
            )
            self._invalidate_cleanup_local_buffer_client(client)
            return 0

    def _get_cleanup_local_buffer_client(self) -> LocalBufferBrokerClient | None:
        """复用父进程 cleanup 控制通道，避免每个 Workflow Run 创建队列。"""

        cleanup_lock = getattr(self, "_cleanup_client_lock", None)
        if cleanup_lock is None:
            cleanup_lock = Lock()
            self._cleanup_client_lock = cleanup_lock
        with cleanup_lock:
            client = getattr(self, "_cleanup_local_buffer_client", None)
            if client is not None:
                return client
            channel = self._resolve_local_buffer_broker_event_channel()
            if channel is None:
                return None
            client = LocalBufferBrokerClient(channel)
            self._cleanup_local_buffer_client = client
            return client

    def _close_cleanup_local_buffer_client(self) -> None:
        """关闭管理器持有的持久化 cleanup 控制通道。"""

        cleanup_lock = getattr(self, "_cleanup_client_lock", None)
        if cleanup_lock is None:
            return
        with cleanup_lock:
            client = getattr(self, "_cleanup_local_buffer_client", None)
            self._cleanup_local_buffer_client = None
        if client is None:
            return
        try:
            client.close()
        except Exception as exc:
            LOGGER.warning("关闭 LocalBufferBroker cleanup client 失败: %s", exc)

    def _invalidate_cleanup_local_buffer_client(
        self,
        client: LocalBufferBrokerClient,
    ) -> None:
        """失效断开的 cleanup client，使后续调用可连接重启后的 broker。"""

        cleanup_lock = getattr(self, "_cleanup_client_lock", None)
        if cleanup_lock is None:
            cleanup_lock = Lock()
            self._cleanup_client_lock = cleanup_lock
        should_close = False
        with cleanup_lock:
            if getattr(self, "_cleanup_local_buffer_client", None) is client:
                self._cleanup_local_buffer_client = None
                should_close = True
        if not should_close:
            return
        try:
            client.close()
        except Exception as exc:  # pragma: no cover - 仅记录关闭兜底失败
            LOGGER.warning("关闭失效 LocalBufferBroker cleanup client 失败: %s", exc)

    def _request_runtime_state(self, handle: _WorkflowRuntimeProcessHandle) -> WorkflowRuntimeWorkerState:
        """向指定 worker 请求当前状态。"""

        with handle.request_lock:
            message_id = uuid4().hex
            return self._wait_for_runtime_state(
                handle,
                message_id=message_id,
                timeout_seconds=5.0,
                payload={
                    "message_type": "health-check",
                    "message_id": message_id,
                    "workflow_runtime_id": handle.workflow_runtime_id,
                },
            )

    def _wait_for_startup_state(
        self,
        handle: _WorkflowRuntimeProcessHandle,
        *,
        timeout_seconds: float,
    ) -> WorkflowRuntimeWorkerState:
        """等待 worker 首次启动状态消息。"""

        started = handle.started_event.wait(timeout=max(0.1, timeout_seconds))
        if not started:
            raise OperationTimeoutError(
                "等待 workflow runtime worker 启动状态超时",
                details={
                    "workflow_runtime_id": handle.workflow_runtime_id,
                    "timeout_seconds": timeout_seconds,
                },
            )
        runtime_state = self._read_cached_runtime_state(handle)
        if runtime_state is None:
            raise ServiceConfigurationError("workflow runtime worker 启动状态缺失")
        return runtime_state

    def _wait_for_runtime_state(
        self,
        handle: _WorkflowRuntimeProcessHandle,
        *,
        message_id: str,
        timeout_seconds: float,
        payload: dict[str, object],
    ) -> WorkflowRuntimeWorkerState:
        """等待 worker 返回 runtime-state 消息。"""

        pending = _WorkflowRuntimePendingResponse()
        with handle.state_lock:
            if not handle.process.is_alive():
                raise ServiceConfigurationError(
                    "workflow runtime worker 当前未运行",
                    details={"workflow_runtime_id": handle.workflow_runtime_id},
                )
            handle.pending_responses[message_id] = pending
            handle.request_queue.put(dict(payload))
        if not pending.event.wait(timeout=max(0.1, timeout_seconds)):
            with handle.state_lock:
                handle.pending_responses.pop(message_id, None)
            raise OperationTimeoutError(
                "等待 workflow runtime worker 状态响应超时",
                details={
                    "workflow_runtime_id": handle.workflow_runtime_id,
                    "timeout_seconds": timeout_seconds,
                },
            )
        message = pending.response or {}
        return self._attach_parent_health_summary(handle, deserialize_runtime_state(message))

    def _read_cached_runtime_state(
        self,
        handle: _WorkflowRuntimeProcessHandle,
    ) -> WorkflowRuntimeWorkerState | None:
        """读取父进程缓存的最新 runtime 状态。"""

        with handle.state_lock:
            return handle.latest_runtime_state

    def _attach_parent_health_summary(
        self,
        handle: _WorkflowRuntimeProcessHandle,
        runtime_state: WorkflowRuntimeWorkerState,
    ) -> WorkflowRuntimeWorkerState:
        """把父进程持有的 broker channel 状态合并到 worker health。"""

        health_summary = dict(runtime_state.health_summary)
        health_summary["parent_local_buffer_broker_channel"] = build_parent_broker_channel_summary(
            handle.local_buffer_broker_event_channel
        )
        return replace(runtime_state, health_summary=health_summary)

    def _terminate_failed_handle(
        self,
        *,
        workflow_runtime_id: str,
        handle: _WorkflowRuntimeProcessHandle,
    ) -> None:
        """在同步调用超时或崩溃后强制清理句柄。"""

        with self._lock:
            self._handles.pop(workflow_runtime_id, None)
        with handle.state_lock:
            handle.expected_shutdown = True
        self._cleanup_handle(handle)

    def _cleanup_handle(self, handle: _WorkflowRuntimeProcessHandle) -> None:
        """关闭并回收一个 worker 句柄。"""

        handle.response_stop_event.set()
        if handle.process.is_alive():
            handle.process.terminate()
            handle.process.join(timeout=1.0)
        response_thread = handle.response_thread
        if response_thread is not None:
            response_thread.join(timeout=1.0)
        if handle.published_inference_gateway_dispatcher is not None:
            handle.published_inference_gateway_dispatcher.stop()
        with handle.state_lock:
            for pending in handle.pending_responses.values():
                pending.error_message = "workflow runtime worker 已退出"
                pending.event.set()
            handle.pending_responses.clear()
        handle.request_queue.close()
        handle.request_queue.join_thread()
        handle.response_queue.close()
        handle.response_queue.join_thread()
        worker_process.close_local_buffer_broker_channel(handle.local_buffer_broker_event_channel)
        worker_process.close_published_inference_gateway_channel(handle.published_inference_gateway_channel)

    def _run_response_loop(self, handle: _WorkflowRuntimeProcessHandle) -> None:
        """持续消费指定 runtime worker 的响应队列。"""

        while not handle.response_stop_event.is_set():
            try:
                message = handle.response_queue.get(timeout=0.2)
            except Empty:
                continue
            except Exception:
                continue
            if not isinstance(message, dict):
                continue

            message_type = str(message.get("message_type") or "")
            request_id = str(message.get("request_id") or "")
            pending: _WorkflowRuntimePendingResponse | None = None

            runtime_state = try_deserialize_runtime_state_message(message)
            if runtime_state is not None:
                runtime_state = self._attach_parent_health_summary(handle, runtime_state)
                should_persist = False
                event_type = "runtime.heartbeat"
                event_message = "workflow app runtime heartbeat"
                with handle.state_lock:
                    handle.latest_runtime_state = runtime_state
                    handle.latest_runtime_state_monotonic = monotonic()
                    handle.background_failure_reported = False
                    if handle.heartbeat_timeout_reported:
                        handle.heartbeat_timeout_reported = False
                        should_persist = True
                        event_type = "runtime.heartbeat_recovered"
                        event_message = "workflow app runtime heartbeat 已恢复"
                    elif message_type == "runtime-heartbeat":
                        should_persist = True
                    if request_id:
                        pending = handle.pending_responses.pop(request_id, None)
                    elif message_type == "runtime-state" and not handle.started_event.is_set():
                        handle.started_event.set()
                if pending is not None:
                    pending.response = message
                    pending.event.set()
                if should_persist:
                    self._persist_runtime_state_event(
                        workflow_runtime_id=handle.workflow_runtime_id,
                        runtime_state=runtime_state,
                        event_type=event_type,
                        message=event_message,
                    )
                continue

            worker_state = try_deserialize_run_result_worker_state(message)
            if worker_state is not None:
                worker_state = self._attach_parent_health_summary(handle, worker_state)
                with handle.state_lock:
                    handle.latest_runtime_state = worker_state
                    handle.latest_runtime_state_monotonic = monotonic()

            if request_id:
                with handle.state_lock:
                    pending = handle.pending_responses.pop(request_id, None)
                if pending is not None:
                    pending.response = message
                    pending.event.set()

    def _run_monitor_loop(self) -> None:
        """巡检 worker 心跳和异常退出，并把异常状态写入正式事件流。"""

        while not self._monitor_stop_event.is_set():
            with self._lock:
                handles = tuple(self._handles.items())
            now = monotonic()
            for workflow_runtime_id, handle in handles:
                runtime_state_to_persist: WorkflowRuntimeWorkerState | None = None
                event_type: str | None = None
                message: str | None = None
                remove_handle = False
                with handle.state_lock:
                    process_alive = handle.process.is_alive()
                    latest_runtime_state = handle.latest_runtime_state
                    latest_runtime_state_monotonic = handle.latest_runtime_state_monotonic
                    if not process_alive:
                        if not handle.expected_shutdown and not handle.background_failure_reported:
                            handle.background_failure_reported = True
                            runtime_state_to_persist = build_synthetic_runtime_state(
                                previous_state=latest_runtime_state,
                                observed_state="failed",
                                last_error="workflow runtime worker 进程已退出",
                            )
                            handle.latest_runtime_state = runtime_state_to_persist
                            handle.latest_runtime_state_monotonic = now
                            event_type = "runtime.failed"
                            message = "workflow runtime worker 进程异常退出"
                        remove_handle = True
                    elif (
                        latest_runtime_state is not None
                        and latest_runtime_state_monotonic is not None
                        and not handle.heartbeat_timeout_reported
                        and now - latest_runtime_state_monotonic > float(handle.heartbeat_timeout_seconds)
                    ):
                        handle.heartbeat_timeout_reported = True
                        runtime_state_to_persist = build_synthetic_runtime_state(
                            previous_state=latest_runtime_state,
                            observed_state="failed",
                            last_error="workflow runtime heartbeat 超时",
                        )
                        handle.latest_runtime_state = runtime_state_to_persist
                        handle.latest_runtime_state_monotonic = now
                        event_type = "runtime.heartbeat_timed_out"
                        message = "workflow app runtime heartbeat 超时"
                if runtime_state_to_persist is not None and event_type is not None and message is not None:
                    self._persist_runtime_state_event(
                        workflow_runtime_id=workflow_runtime_id,
                        runtime_state=runtime_state_to_persist,
                        event_type=event_type,
                        message=message,
                    )
                if remove_handle:
                    with self._lock:
                        stored_handle = self._handles.get(workflow_runtime_id)
                        if stored_handle is handle:
                            self._handles.pop(workflow_runtime_id, None)
                    self._cleanup_handle(handle)
            self._monitor_stop_event.wait(0.5)

    def _persist_runtime_state_event(
        self,
        *,
        workflow_runtime_id: str,
        runtime_state: WorkflowRuntimeWorkerState,
        event_type: str,
        message: str,
    ) -> None:
        """把后台 runtime 状态变化回写到 DB 和 events.json。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            workflow_app_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(workflow_runtime_id)
            if workflow_app_runtime is None:
                return
            updated_runtime = replace(
                workflow_app_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=now_isoformat(),
                heartbeat_at=runtime_state.heartbeat_at,
                worker_process_id=runtime_state.process_id,
                loaded_snapshot_fingerprint=runtime_state.loaded_snapshot_fingerprint,
                last_error=runtime_state.last_error,
                health_summary=dict(runtime_state.health_summary),
            )
            unit_of_work.workflow_runtime.save_workflow_app_runtime(updated_runtime)
            unit_of_work.commit()
        finally:
            unit_of_work.close()
        append_workflow_app_runtime_event(
            dataset_storage=self.dataset_storage,
            service_event_bus=self.service_event_bus,
            session_factory=self.session_factory,
            workflow_app_runtime=updated_runtime,
            event_type=event_type,
            message=message,
        )

    def _resolve_runtime_start_timeout_seconds(self) -> float:
        """返回 runtime worker 启动阶段的控制面等待超时。"""

        configured_timeout_seconds = float(
            self.settings.deployment_process_supervisor.startup_timeout_seconds
        )
        return max(configured_timeout_seconds, 5.0)

    def _resolve_local_buffer_broker_event_channel(self) -> LocalBufferBrokerEventChannel | None:
        """读取当前 broker 事件通道。"""

        if self.local_buffer_broker_event_channel_provider is None:
            return None
        return self.local_buffer_broker_event_channel_provider()

    def _build_published_inference_gateway_channel(self) -> PublishedInferenceGatewayEventChannel | None:
        """为一个 runtime worker 创建 PublishedInferenceGateway 事件通道。"""

        if self.published_inference_gateway is None:
            return None
        from backend.service.application.deployments import PublishedInferenceGatewayEventChannel

        return PublishedInferenceGatewayEventChannel(
            request_queue=self._context.Queue(),
            response_queue=self._context.Queue(),
            request_timeout_seconds=self.settings.deployment_process_supervisor.request_timeout_seconds,
        )

    def _build_published_inference_gateway_dispatcher(
        self,
        channel: PublishedInferenceGatewayEventChannel | None,
    ) -> PublishedInferenceGatewayDispatcher | None:
        """为一个 runtime worker 创建父进程 gateway dispatcher。"""

        if channel is None or self.published_inference_gateway is None:
            return None
        from backend.service.application.deployments import PublishedInferenceGatewayDispatcher

        return PublishedInferenceGatewayDispatcher(channel=channel, gateway=self.published_inference_gateway)


def _elapsed_ms(started_at: float) -> float:
    """把 monotonic 起点转换为毫秒耗时。"""

    return round((monotonic() - started_at) * 1000.0, 3)
