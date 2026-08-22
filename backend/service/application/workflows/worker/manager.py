"""workflow runtime worker 管理器。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from queue import Empty
from threading import Event, Lock, RLock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Any, Iterator
from uuid import uuid4
import logging
import multiprocessing

from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ResourceConflictError,
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
from backend.service.application.workflows.runtime_app_events import (
    append_workflow_app_runtime_event,
)
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
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
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
    workflow_runtime_revision_id: str | None = None
    runtime_generation: int = 0
    expected_snapshot_fingerprint: str | None = None
    worker_instance_id: str | None = None
    local_buffer_broker_event_channel: LocalBufferBrokerEventChannel | None = None
    published_inference_gateway_channel: (
        PublishedInferenceGatewayEventChannel | None
    ) = None
    published_inference_gateway_dispatcher: (
        PublishedInferenceGatewayDispatcher | None
    ) = None
    heartbeat_interval_seconds: int = 5
    heartbeat_timeout_seconds: int = 15
    response_thread: Thread | None = None
    response_stop_event: Event = field(default_factory=Event, repr=False)
    pending_responses: dict[str, _WorkflowRuntimePendingResponse] = field(
        default_factory=dict, repr=False
    )
    started_event: Event = field(default_factory=Event, repr=False)
    request_lock: Lock = field(default_factory=Lock, repr=False)
    state_lock: Lock = field(default_factory=Lock, repr=False)
    cleanup_lock: Lock = field(default_factory=Lock, repr=False)
    latest_runtime_state: WorkflowRuntimeWorkerState | None = None
    latest_runtime_state_monotonic: float | None = None
    expected_shutdown: bool = False
    cleanup_completed: bool = False
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
    expected_revision_id: str | None
    expected_generation: int | None
    expected_snapshot_fingerprint: str | None
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
        local_buffer_broker_event_channel_provider: Callable[
            [], LocalBufferBrokerEventChannel | None
        ]
        | None = None,
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
        self.local_buffer_broker_event_channel_provider = (
            local_buffer_broker_event_channel_provider
        )
        self.published_inference_gateway = published_inference_gateway
        self._context = multiprocessing.get_context("spawn")
        self._handles: dict[str, _WorkflowRuntimeProcessHandle] = {}
        self._async_runs: dict[str, _WorkflowRuntimeAsyncRunHandle] = {}
        self._sync_admissions: dict[str, set[str]] = {}
        self._lock = Lock()
        self._stopping = Event()
        self._monitor_stop_event = Event()
        self._monitor_thread: Thread | None = None
        self._recovery_threads: dict[str, Thread] = {}
        self._recovery_failures: dict[str, int] = {}
        self._recovery_next_attempt_at: dict[str, float] = {}
        # 使用固定数量的分段锁串行化同一 runtime 的显式生命周期操作与
        # monitor 自动恢复，避免为历史 runtime id 无限保留独立锁。
        self._runtime_lifecycle_locks = tuple(RLock() for _ in range(64))
        self._cleanup_client_lock = Lock()
        self._cleanup_local_buffer_client: LocalBufferBrokerClient | None = None

    def start(self) -> None:
        """启动管理器本身。

        启动返回前先恢复持久化为 desired=running 的 Runtime，确保随后启动的
        TriggerSource 不会在 worker 尚未就绪时接收首批外部请求。
        """

        self._stopping.clear()
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._recover_desired_runtimes_before_monitor()
            self._monitor_stop_event.clear()
            self._monitor_thread = Thread(
                target=self._run_monitor_loop,
                name="workflow-runtime-worker-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def _recover_desired_runtimes_before_monitor(self) -> None:
        """按配置并行度完成一次有界启动恢复，并等待每个恢复任务结束。"""

        pending = list(self._load_recoverable_desired_runtimes())
        max_parallel = max(
            1,
            self.settings.workflow_runtime.model_startup_parallelism,
        )
        while pending and not self._stopping.is_set():
            batch = pending[:max_parallel]
            del pending[:max_parallel]
            threads: list[Thread] = []
            for workflow_app_runtime in batch:
                runtime_id = workflow_app_runtime.workflow_runtime_id
                if self.is_runtime_available(runtime_id):
                    continue
                recovery_thread = Thread(
                    target=self._recover_desired_runtime,
                    args=(workflow_app_runtime,),
                    name=f"workflow-runtime-startup-recovery-{runtime_id}",
                    daemon=True,
                )
                with self._lock:
                    self._recovery_threads[runtime_id] = recovery_thread
                recovery_thread.start()
                threads.append(recovery_thread)
            for recovery_thread in threads:
                recovery_thread.join()

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
        with self._lock:
            recovery_threads = tuple(self._recovery_threads.values())
        for recovery_thread in recovery_threads:
            recovery_thread.join(timeout=1.0)
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

    def start_runtime(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        workflow_runtime_revision_id: str | None = None,
        runtime_generation: int | None = None,
        expected_snapshot_fingerprint: str | None = None,
    ) -> WorkflowRuntimeWorkerState:
        """拉起一个 runtime 对应的单实例 worker 进程。"""

        with self._resolve_runtime_lifecycle_lock(
            workflow_app_runtime.workflow_runtime_id
        ):
            return self._start_runtime(
                workflow_app_runtime,
                workflow_runtime_revision_id=workflow_runtime_revision_id,
                runtime_generation=runtime_generation,
                expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            )

    def _start_runtime(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        workflow_runtime_revision_id: str | None = None,
        runtime_generation: int | None = None,
        expected_snapshot_fingerprint: str | None = None,
    ) -> WorkflowRuntimeWorkerState:
        """在当前 runtime 生命周期锁内拉起 worker 进程。"""

        resolved_revision_id = (
            workflow_runtime_revision_id
            or workflow_app_runtime.desired_revision_id
            or workflow_app_runtime.active_revision_id
        )
        if resolved_revision_id is None:
            raise ServiceConfigurationError(
                "workflow runtime worker 启动时缺少 revision id"
            )
        resolved_generation = (
            workflow_app_runtime.revision_generation
            if runtime_generation is None
            else runtime_generation
        )
        resolved_fingerprint = (
            expected_snapshot_fingerprint
            or workflow_app_runtime.loaded_snapshot_fingerprint
        )
        worker_instance_id = f"{workflow_app_runtime.workflow_runtime_id}-{uuid4().hex}"

        with self._lock:
            existing_handle = self._handles.get(
                workflow_app_runtime.workflow_runtime_id
            )
            if existing_handle is not None and existing_handle.process.is_alive():
                existing_state = self._read_cached_runtime_state(
                    existing_handle
                ) or self._request_runtime_state(existing_handle)
                if existing_state.observed_state == "running":
                    if (
                        existing_handle.workflow_runtime_revision_id
                        != resolved_revision_id
                        or existing_handle.runtime_generation != resolved_generation
                        or (
                            resolved_fingerprint is not None
                            and existing_handle.expected_snapshot_fingerprint
                            != resolved_fingerprint
                        )
                    ):
                        raise ResourceConflictError(
                            "WorkflowAppRuntime 已由另一版本的 worker 占用"
                        )
                    return existing_state
                self._cleanup_handle(existing_handle)
                if (
                    self._handles.get(workflow_app_runtime.workflow_runtime_id)
                    is existing_handle
                ):
                    self._handles.pop(
                        workflow_app_runtime.workflow_runtime_id,
                        None,
                    )
            elif existing_handle is not None:
                self._cleanup_handle(existing_handle)
                if (
                    self._handles.get(workflow_app_runtime.workflow_runtime_id)
                    is existing_handle
                ):
                    self._handles.pop(
                        workflow_app_runtime.workflow_runtime_id,
                        None,
                    )

            request_queue = self._context.Queue()
            response_queue = self._context.Queue()
            local_buffer_broker_event_channel = (
                self._resolve_local_buffer_broker_event_channel()
            )
            gateway_channel = self._build_published_inference_gateway_channel()
            gateway_dispatcher = self._build_published_inference_gateway_dispatcher(
                gateway_channel
            )
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
                        "workflow_runtime_revision_id": resolved_revision_id,
                        "runtime_generation": resolved_generation,
                        "expected_snapshot_fingerprint": resolved_fingerprint,
                        "worker_instance_id": worker_instance_id,
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
                workflow_runtime_revision_id=resolved_revision_id,
                runtime_generation=resolved_generation,
                expected_snapshot_fingerprint=resolved_fingerprint,
                worker_instance_id=worker_instance_id,
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

        try:
            runtime_state = self._wait_for_startup_state(
                handle,
                timeout_seconds=self._resolve_runtime_start_timeout_seconds(
                    has_model_loaders=self._snapshot_has_model_loaders(
                        workflow_app_runtime.template_snapshot_object_key
                    )
                ),
            )
            if runtime_state.instance_id != worker_instance_id:
                raise ServiceConfigurationError(
                    "workflow runtime worker instance id 不匹配"
                )
            if (
                resolved_fingerprint is not None
                and runtime_state.loaded_snapshot_fingerprint != resolved_fingerprint
            ):
                raise ServiceConfigurationError(
                    "workflow runtime worker snapshot 指纹不匹配",
                    details={
                        "expected": resolved_fingerprint,
                        "actual": runtime_state.loaded_snapshot_fingerprint,
                    },
                )
            if handle.expected_snapshot_fingerprint is None:
                handle.expected_snapshot_fingerprint = (
                    runtime_state.loaded_snapshot_fingerprint
                )
            # worker 只有在 startup 状态、epoch 和快照指纹全部校验通过后才可见。
            # 否则取消后的重建窗口会暴露“进程存活但尚未 ready”的 handle，
            # health 可能向仍在初始化的子进程发送请求并误报 504。
            with self._lock:
                if self._stopping.is_set():
                    raise ServiceConfigurationError(
                        "workflow runtime worker manager 已在启动期间停止"
                    )
                if (
                    self._handles.get(workflow_app_runtime.workflow_runtime_id)
                    is not None
                ):
                    raise ResourceConflictError(
                        "WorkflowAppRuntime worker 启动完成前已被另一进程接管"
                    )
                self._handles[workflow_app_runtime.workflow_runtime_id] = handle
            return runtime_state
        except Exception:
            self._remove_handle_if_current(
                workflow_app_runtime.workflow_runtime_id,
                handle,
            )
            self._cleanup_handle(handle)
            raise

    def stop_runtime(self, workflow_runtime_id: str) -> WorkflowRuntimeWorkerState:
        """停止一个 runtime 对应的 worker 进程。"""

        with self._resolve_runtime_lifecycle_lock(workflow_runtime_id):
            return self._stop_runtime(workflow_runtime_id)

    def _stop_runtime(self, workflow_runtime_id: str) -> WorkflowRuntimeWorkerState:
        """在当前 runtime 生命周期锁内停止 worker 进程。"""

        with self._lock:
            handle = self._handles.get(workflow_runtime_id)
        if handle is None:
            return WorkflowRuntimeWorkerState(observed_state="stopped")

        if not handle.process.is_alive():
            self._remove_handle_if_current(workflow_runtime_id, handle)
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
        self._remove_handle_if_current(workflow_runtime_id, handle)
        self._cleanup_handle(handle)
        return runtime_state

    def restart_runtime(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        workflow_runtime_revision_id: str | None = None,
        runtime_generation: int | None = None,
        expected_snapshot_fingerprint: str | None = None,
    ) -> WorkflowRuntimeWorkerState:
        """在同一生命周期临界区内停止并重新拉起 runtime worker。"""

        workflow_runtime_id = workflow_app_runtime.workflow_runtime_id
        with self._resolve_runtime_lifecycle_lock(workflow_runtime_id):
            self._stop_runtime(workflow_runtime_id)
            return self._start_runtime(
                workflow_app_runtime,
                workflow_runtime_revision_id=workflow_runtime_revision_id,
                runtime_generation=runtime_generation,
                expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            )

    def get_runtime_health(
        self, workflow_runtime_id: str
    ) -> WorkflowRuntimeWorkerState:
        """查询一个 runtime 对应 worker 的健康状态。"""

        # start/restart/recovery 会在同一 lifecycle 锁内等待 worker startup-ready。
        # health 也经过该栅栏，既不会把尚未发布的新 worker 当成 stopped，也不会
        # 对初始化中的进程发 health-check；正常运行时这里只是一次无竞争 RLock。
        with self._resolve_runtime_lifecycle_lock(workflow_runtime_id):
            while True:
                with self._lock:
                    handle = self._handles.get(workflow_runtime_id)
                if handle is None:
                    return WorkflowRuntimeWorkerState(observed_state="stopped")
                if not handle.process.is_alive():
                    removed = self._remove_handle_if_current(
                        workflow_runtime_id,
                        handle,
                    )
                    self._cleanup_handle(handle)
                    if not removed:
                        # 旧 handle 检查期间已有新 worker 接管稳定 runtime id；
                        # 重新读取新句柄，不能把旧进程失败返回成当前健康状态。
                        continue
                    return WorkflowRuntimeWorkerState(
                        observed_state="failed",
                        last_error="workflow runtime worker 进程已退出",
                    )
                cached_state = self._read_cached_runtime_state(handle)
                with self._lock:
                    if self._handles.get(workflow_runtime_id) is not handle:
                        continue
                if cached_state is not None:
                    return cached_state
                return self._request_runtime_state(handle)

    def list_runtime_instances(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRuntimeWorkerInstance, ...]:
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
        expected_revision_id: str | None = None,
        expected_generation: int | None = None,
        expected_snapshot_fingerprint: str | None = None,
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
            raise ServiceConfigurationError(
                "workflow runtime worker manager 当前已停止"
            )
        if not self.is_runtime_available(workflow_app_runtime.workflow_runtime_id):
            self.cleanup_parent_local_buffer_leases(execution_metadata)
            raise ServiceConfigurationError(
                "workflow runtime worker 当前未运行",
                details={
                    "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id
                },
            )

        async_handle = _WorkflowRuntimeAsyncRunHandle(
            workflow_app_runtime=workflow_app_runtime,
            workflow_run_id=workflow_run_id,
            input_bindings=dict(input_bindings),
            execution_metadata=dict(execution_metadata),
            timeout_seconds=timeout_seconds,
            expected_revision_id=expected_revision_id,
            expected_generation=expected_generation,
            expected_snapshot_fingerprint=expected_snapshot_fingerprint,
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

    def cancel_async_run(
        self, workflow_run_id: str, *, timeout_seconds: float = 10.0
    ) -> bool:
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
        expected_revision_id: str | None = None,
        expected_generation: int | None = None,
        expected_snapshot_fingerprint: str | None = None,
        cancel_event: Event | None = None,
        on_dispatched: Callable[[], None] | None = None,
    ) -> WorkflowRuntimeWorkerRunResult:
        """通过已运行的 worker 发起一次同步调用。"""

        invoke_started_at = monotonic()
        deadline = invoke_started_at + float(timeout_seconds)
        lock_acquired = False
        lock_wait_started_at = monotonic()
        lifecycle_lock = self._resolve_runtime_lifecycle_lock(
            workflow_app_runtime.workflow_runtime_id
        )
        lifecycle_lock_acquired = False
        try:
            while not lifecycle_lock_acquired:
                if cancel_event is not None and cancel_event.is_set():
                    raise OperationCancelledError(
                        "workflow run 已取消",
                        details={
                            "workflow_runtime_id": (
                                workflow_app_runtime.workflow_runtime_id
                            ),
                            "workflow_run_id": workflow_run_id,
                        },
                    )
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    raise OperationTimeoutError(
                        "等待 workflow runtime 生命周期操作完成超时",
                        details={
                            "workflow_runtime_id": (
                                workflow_app_runtime.workflow_runtime_id
                            ),
                            "workflow_run_id": workflow_run_id,
                            "timeout_seconds": timeout_seconds,
                            "timeout_phase": "runtime_lifecycle_lock",
                        },
                    )
                lifecycle_lock_acquired = lifecycle_lock.acquire(
                    timeout=max(0.001, min(0.1, remaining_seconds))
                )

            with self._lock:
                handle = self._handles.get(workflow_app_runtime.workflow_runtime_id)
            if handle is None or not handle.process.is_alive():
                raise ServiceConfigurationError(
                    "workflow runtime worker 当前未运行",
                    details={
                        "workflow_runtime_id": (
                            workflow_app_runtime.workflow_runtime_id
                        )
                    },
                )
            self._validate_handle_identity(
                handle,
                workflow_app_runtime=workflow_app_runtime,
                expected_revision_id=expected_revision_id,
                expected_generation=expected_generation,
                expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            )
            while not lock_acquired:
                if cancel_event is not None and cancel_event.is_set():
                    raise OperationCancelledError(
                        "workflow run 已取消",
                        details={
                            "workflow_runtime_id": (
                                workflow_app_runtime.workflow_runtime_id
                            ),
                            "workflow_run_id": workflow_run_id,
                        },
                    )
                if not handle.process.is_alive():
                    self._terminate_failed_handle(
                        workflow_runtime_id=(workflow_app_runtime.workflow_runtime_id),
                        handle=handle,
                    )
                    raise ServiceConfigurationError(
                        "workflow runtime worker 当前未运行",
                        details={
                            "workflow_runtime_id": (
                                workflow_app_runtime.workflow_runtime_id
                            )
                        },
                    )
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    raise OperationTimeoutError(
                        "等待 workflow runtime worker 可用执行槽位超时",
                        details={
                            "workflow_runtime_id": (
                                workflow_app_runtime.workflow_runtime_id
                            ),
                            "workflow_run_id": workflow_run_id,
                            "timeout_seconds": timeout_seconds,
                            "timeout_phase": "request_lock",
                        },
                    )
                lock_acquired = handle.request_lock.acquire(
                    timeout=max(0.001, min(0.1, remaining_seconds))
                )
            with self._lock:
                current_handle = self._handles.get(
                    workflow_app_runtime.workflow_runtime_id
                )
            if current_handle is not handle:
                handle.request_lock.release()
                lock_acquired = False
                raise ResourceConflictError(
                    "WorkflowAppRuntime worker 已在调用前切换版本",
                    details={
                        "workflow_runtime_id": (
                            workflow_app_runtime.workflow_runtime_id
                        )
                    },
                )
            self._validate_handle_identity(
                handle,
                workflow_app_runtime=workflow_app_runtime,
                expected_revision_id=expected_revision_id,
                expected_generation=expected_generation,
                expected_snapshot_fingerprint=expected_snapshot_fingerprint,
            )
        except Exception:
            if lock_acquired:
                try:
                    handle.request_lock.release()
                except RuntimeError:
                    pass
                lock_acquired = False
            raise
        finally:
            if lifecycle_lock_acquired:
                lifecycle_lock.release()
        request_lock_wait_ms = _elapsed_ms(lock_wait_started_at)
        worker_process_id = handle.process.pid

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
                        details={
                            "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id
                        },
                    )
                handle.pending_responses[message_id] = pending
                queue_put_started_at = monotonic()
                handle.request_queue.put(
                    {
                        "message_type": "invoke-run",
                        "message_id": message_id,
                        "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                        "workflow_run_id": workflow_run_id,
                        "workflow_runtime_revision_id": (
                            expected_revision_id
                            or workflow_app_runtime.active_revision_id
                        ),
                        "runtime_generation": (
                            workflow_app_runtime.revision_generation
                            if expected_generation is None
                            else expected_generation
                        ),
                        "expected_snapshot_fingerprint": (
                            expected_snapshot_fingerprint
                            or workflow_app_runtime.loaded_snapshot_fingerprint
                        ),
                        "worker_instance_id": handle.worker_instance_id,
                        "requested_timeout_seconds": timeout_seconds,
                        "input_bindings": dict(input_bindings),
                        "execution_metadata": process_execution_metadata,
                    }
                )
                request_queue_put_ms = _elapsed_ms(queue_put_started_at)
            if on_dispatched is not None:
                on_dispatched()

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
                            "worker_process_id": worker_process_id,
                            "worker_instance_id": handle.worker_instance_id,
                            "timeout_seconds": timeout_seconds,
                        },
                    )
                if pending.event.wait(timeout=max(0.1, min(0.2, remaining_seconds))):
                    if pending.error_message is not None:
                        raise ServiceConfigurationError(
                            pending.error_message,
                            details={
                                "workflow_runtime_id": (
                                    workflow_app_runtime.workflow_runtime_id
                                ),
                                "workflow_run_id": workflow_run_id,
                            },
                        )
                    message = pending.response or {}
                    worker_response_received = True
                    worker_reply_wait_ms = _elapsed_ms(reply_wait_started_at)
                    break
                if not handle.process.is_alive():
                    process_exit_code = handle.process.exitcode
                    self._terminate_failed_handle(
                        workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
                        handle=handle,
                    )
                    raise ServiceConfigurationError(
                        "workflow runtime worker 进程已退出",
                        details={
                            "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                            "workflow_run_id": workflow_run_id,
                            "process_exit_code": process_exit_code,
                        },
                    )
        finally:
            if lock_acquired:
                try:
                    handle.request_lock.release()
                except RuntimeError:
                    pass
            with handle.state_lock:
                handle.pending_responses.pop(
                    message_id if "message_id" in locals() else "", None
                )
            if "message_id" in locals():
                self.cleanup_workflow_run_local_buffer_owner(workflow_run_id)
            if not locals().get("worker_response_received", False):
                # worker 未返回时无法确认其 finally 是否运行；覆盖入队失败、取消、
                # 超时和进程硬退出，释放 TriggerSource 输入等父进程已知 lease。
                self.cleanup_parent_local_buffer_leases(execution_metadata)

        self._validate_worker_response_identity(message, handle)
        worker_result = deserialize_run_result(message)
        timings = dict(worker_result.timings)
        timings.update(
            {
                "worker_request_lock_wait_ms": request_lock_wait_ms,
                "worker_request_queue_put_ms": request_queue_put_ms
                if "request_queue_put_ms" in locals()
                else None,
                "worker_reply_wait_ms": worker_reply_wait_ms
                if "worker_reply_wait_ms" in locals()
                else None,
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
                expected_revision_id=async_handle.expected_revision_id,
                expected_generation=async_handle.expected_generation,
                expected_snapshot_fingerprint=(
                    async_handle.expected_snapshot_fingerprint
                ),
                cancel_event=async_handle.cancel_event,
                on_dispatched=lambda: self._mark_async_run_dispatched(async_handle),
            )
            async_handle.callbacks.on_completed(worker_result)
        except OperationCancelledError:
            self.cleanup_parent_local_buffer_leases(async_handle.execution_metadata)
            # 取消状态和 run.cancelled 事件必须先对外可见，不能被后续 worker
            # 恢复启动耗时阻塞。恢复属于 runtime 生命周期，不是本次 run 的完成条件。
            try:
                async_handle.callbacks.on_cancelled(None)
            except Exception:  # noqa: BLE001 - run 状态持久化失败不能阻止 worker 恢复
                LOGGER.exception(
                    "workflow run 取消状态回写失败: workflow_run_id=%s",
                    async_handle.workflow_run_id,
                )
            if async_handle.dispatched_event.is_set() and not self._stopping.is_set():
                self._recover_cancelled_async_runtime(async_handle)
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

    def _recover_cancelled_async_runtime(
        self,
        async_handle: _WorkflowRuntimeAsyncRunHandle,
    ) -> None:
        """仅在 Runtime 仍固定到本次异步请求版本时恢复被取消的 worker。"""

        workflow_runtime_id = async_handle.workflow_app_runtime.workflow_runtime_id
        expected_revision_id = (
            async_handle.expected_revision_id
            or async_handle.workflow_app_runtime.active_revision_id
        )
        expected_generation = (
            async_handle.workflow_app_runtime.revision_generation
            if async_handle.expected_generation is None
            else async_handle.expected_generation
        )
        expected_fingerprint = (
            async_handle.expected_snapshot_fingerprint
            or async_handle.workflow_app_runtime.loaded_snapshot_fingerprint
        )
        if expected_revision_id is None or expected_fingerprint is None:
            return

        with self._resolve_runtime_lifecycle_lock(workflow_runtime_id):
            recovery_target = self._get_recoverable_runtime_target(workflow_runtime_id)
            if recovery_target is None:
                return
            latest, revision_fingerprint = recovery_target
            if (
                latest.active_revision_id != expected_revision_id
                or latest.desired_revision_id != expected_revision_id
                or latest.revision_generation != expected_generation
                or revision_fingerprint != expected_fingerprint
            ):
                # 旧异步任务的取消不能接管已经切换版本的稳定 Runtime id。
                return
            with self._lock:
                current_handle = self._handles.get(workflow_runtime_id)
            if current_handle is not None and current_handle.process.is_alive():
                return

            stored_worker_instance_id = latest.worker_instance_id
            try:
                runtime_state = self._start_runtime(
                    latest,
                    workflow_runtime_revision_id=expected_revision_id,
                    runtime_generation=expected_generation,
                    expected_snapshot_fingerprint=expected_fingerprint,
                )
            except ServiceError as error:
                failed_state = WorkflowRuntimeWorkerState(
                    observed_state="failed",
                    instance_id=stored_worker_instance_id,
                    loaded_snapshot_fingerprint=expected_fingerprint,
                    last_error=error.message,
                    health_summary={
                        "mode": "single-instance-sync",
                        "worker_state": "failed",
                        "last_error": error.message,
                    },
                )
                self._persist_runtime_state_event(
                    workflow_runtime_id=workflow_runtime_id,
                    runtime_state=failed_state,
                    event_type="runtime.failed",
                    message="workflow app runtime 在取消后进入失败状态",
                    expected_revision_id=expected_revision_id,
                    expected_generation=expected_generation,
                    expected_snapshot_fingerprint=expected_fingerprint,
                    expected_worker_instance_id=stored_worker_instance_id,
                    source_worker_instance_id=stored_worker_instance_id,
                )
                return

            with self._lock:
                recovered_handle = self._handles.get(workflow_runtime_id)
            persisted = self._persist_runtime_state_event(
                workflow_runtime_id=workflow_runtime_id,
                runtime_state=runtime_state,
                event_type="runtime.restarted",
                message="workflow app runtime 已在取消后恢复运行",
                expected_revision_id=expected_revision_id,
                expected_generation=expected_generation,
                expected_snapshot_fingerprint=expected_fingerprint,
                expected_worker_instance_id=stored_worker_instance_id,
                source_worker_instance_id=runtime_state.instance_id,
                source_handle=recovered_handle,
            )
            if not persisted:
                self._stop_runtime(workflow_runtime_id)

    @staticmethod
    def _mark_async_run_dispatched(
        async_handle: _WorkflowRuntimeAsyncRunHandle,
    ) -> None:
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
                    pool_name=pool_name_value
                    if isinstance(pool_name_value, str)
                    else None,
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

    def _request_runtime_state(
        self, handle: _WorkflowRuntimeProcessHandle
    ) -> WorkflowRuntimeWorkerState:
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

        deadline = monotonic() + max(0.1, timeout_seconds)
        while not handle.started_event.wait(timeout=0.1):
            if not handle.process.is_alive():
                process_exit_code = handle.process.exitcode
                raise ServiceConfigurationError(
                    "workflow runtime worker 在启动完成前退出",
                    details={
                        "workflow_runtime_id": handle.workflow_runtime_id,
                        "process_exit_code": process_exit_code,
                    },
                )
            if monotonic() >= deadline:
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
        if pending.error_message is not None:
            raise ServiceConfigurationError(
                pending.error_message,
                details={"workflow_runtime_id": handle.workflow_runtime_id},
            )
        return self._attach_parent_health_summary(
            handle, deserialize_runtime_state(message)
        )

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
        health_summary["parent_local_buffer_broker_channel"] = (
            build_parent_broker_channel_summary(
                handle.local_buffer_broker_event_channel
            )
        )
        return replace(runtime_state, health_summary=health_summary)

    def _terminate_failed_handle(
        self,
        *,
        workflow_runtime_id: str,
        handle: _WorkflowRuntimeProcessHandle,
    ) -> None:
        """在同步调用超时或崩溃后强制清理句柄。"""

        self._remove_handle_if_current(workflow_runtime_id, handle)
        with handle.state_lock:
            handle.expected_shutdown = True
        self._cleanup_handle(handle)

    def _remove_handle_if_current(
        self,
        workflow_runtime_id: str,
        handle: _WorkflowRuntimeProcessHandle,
    ) -> bool:
        """只移除调用方实际观察到的 handle，避免误删后继 worker。"""

        with self._lock:
            if self._handles.get(workflow_runtime_id) is not handle:
                return False
            self._handles.pop(workflow_runtime_id, None)
            return True

    def _cleanup_handle(self, handle: _WorkflowRuntimeProcessHandle) -> None:
        """按单一所有权关闭并回收一个 worker 句柄。"""

        # monitor、显式 stop/restart 和 startup 失败可能同时观察到同一个旧
        # handle。清理锁保证 Queue、Process 和 dispatcher 只由一个调用方
        # 关闭；expected_shutdown 让尚未进入清理的 monitor 不再重复接管。
        with handle.cleanup_lock:
            if handle.cleanup_completed:
                return
            with handle.state_lock:
                handle.expected_shutdown = True

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
            worker_process.close_local_buffer_broker_channel(
                handle.local_buffer_broker_event_channel
            )
            worker_process.close_published_inference_gateway_channel(
                handle.published_inference_gateway_channel
            )
            handle.cleanup_completed = True

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
            try:
                self._validate_worker_response_identity(message, handle)
            except ServiceError as error:
                LOGGER.warning(
                    "丢弃身份不匹配的 workflow worker 消息: runtime_id=%s type=%s error=%s",
                    handle.workflow_runtime_id,
                    message_type,
                    error.message,
                )
                if request_id:
                    with handle.state_lock:
                        pending = handle.pending_responses.pop(request_id, None)
                    if pending is not None:
                        pending.error_message = error.message
                        pending.event.set()
                continue

            runtime_state = try_deserialize_runtime_state_message(message)
            if runtime_state is not None:
                runtime_state = self._attach_parent_health_summary(
                    handle, runtime_state
                )
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
                    elif (
                        message_type == "runtime-state"
                        and not handle.started_event.is_set()
                    ):
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
                        expected_revision_id=(handle.workflow_runtime_revision_id),
                        expected_generation=handle.runtime_generation,
                        expected_snapshot_fingerprint=(
                            handle.expected_snapshot_fingerprint
                        ),
                        expected_worker_instance_id=handle.worker_instance_id,
                        source_worker_instance_id=handle.worker_instance_id,
                        source_handle=handle,
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
                    latest_runtime_state_monotonic = (
                        handle.latest_runtime_state_monotonic
                    )
                    if not process_alive:
                        if handle.expected_shutdown:
                            # stop/restart 调用方持有生命周期锁并负责移除、回收句柄；
                            # monitor 不能并发关闭相同 Queue/Process 资源。
                            continue
                        if not handle.background_failure_reported:
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
                        and now - latest_runtime_state_monotonic
                        > float(handle.heartbeat_timeout_seconds)
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
                if (
                    runtime_state_to_persist is not None
                    and event_type is not None
                    and message is not None
                ):
                    self._persist_runtime_state_event(
                        workflow_runtime_id=workflow_runtime_id,
                        runtime_state=runtime_state_to_persist,
                        event_type=event_type,
                        message=message,
                        expected_revision_id=(handle.workflow_runtime_revision_id),
                        expected_generation=handle.runtime_generation,
                        expected_snapshot_fingerprint=(
                            handle.expected_snapshot_fingerprint
                        ),
                        expected_worker_instance_id=handle.worker_instance_id,
                        source_worker_instance_id=handle.worker_instance_id,
                        source_handle=handle,
                    )
                if remove_handle:
                    with self._lock:
                        stored_handle = self._handles.get(workflow_runtime_id)
                        if stored_handle is handle:
                            self._handles.pop(workflow_runtime_id, None)
                    self._cleanup_handle(handle)
            try:
                self._schedule_desired_runtime_recoveries()
            except Exception:  # noqa: BLE001 - 数据库暂时不可用不能终止监控线程
                LOGGER.exception("扫描 WorkflowAppRuntime 自动恢复状态失败")
            self._monitor_stop_event.wait(0.5)

    def _schedule_desired_runtime_recoveries(self) -> None:
        """扫描 desired=running 记录并并行调度缺失 worker 的恢复。"""

        if self._stopping.is_set():
            return
        recoverable_runtimes = self._load_recoverable_desired_runtimes()
        now = monotonic()
        max_parallel = max(1, self.settings.workflow_runtime.model_startup_parallelism)
        for workflow_app_runtime in recoverable_runtimes:
            runtime_id = workflow_app_runtime.workflow_runtime_id
            if self.is_runtime_available(runtime_id):
                continue
            with self._lock:
                # 异步 run 的数据库终态会先于事件追加完成。必须等回调完整返回后
                # 再恢复 worker，避免 runtime.recovered 先于 runtime.failed 发布，
                # 也避免请求上下文结束时仍有后台线程写临时存储。
                if any(
                    async_handle.workflow_app_runtime.workflow_runtime_id == runtime_id
                    for async_handle in self._async_runs.values()
                ):
                    continue
                recovery_thread = self._recovery_threads.get(runtime_id)
                if recovery_thread is not None and recovery_thread.is_alive():
                    continue
                active_count = sum(
                    1 for item in self._recovery_threads.values() if item.is_alive()
                )
                if active_count >= max_parallel:
                    break
                if self._recovery_next_attempt_at.get(runtime_id, 0.0) > now:
                    continue
                recovery_thread = Thread(
                    target=self._recover_desired_runtime,
                    args=(workflow_app_runtime,),
                    name=f"workflow-runtime-recovery-{runtime_id}",
                    daemon=True,
                )
                self._recovery_threads[runtime_id] = recovery_thread
                recovery_thread.start()

    def _load_recoverable_desired_runtimes(
        self,
    ) -> tuple[WorkflowAppRuntime, ...]:
        """读取 active revision 与当前 generation 一致的期望运行 Runtime。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            desired_runtimes = unit_of_work.workflow_runtime.list_workflow_app_runtimes_by_desired_state(
                "running"
            )
            recoverable_runtimes: list[WorkflowAppRuntime] = []
            for workflow_app_runtime in desired_runtimes:
                if workflow_app_runtime.desired_revision_id is None:
                    continue
                desired_revision = (
                    unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                        workflow_app_runtime.desired_revision_id
                    )
                )
                if (
                    desired_revision is not None
                    and desired_revision.state == "active"
                    and workflow_app_runtime.active_revision_id
                    == desired_revision.workflow_runtime_revision_id
                    and workflow_app_runtime.revision_generation
                    == desired_revision.generation
                ):
                    recoverable_runtimes.append(workflow_app_runtime)
        finally:
            unit_of_work.close()
        return tuple(recoverable_runtimes)

    def _recover_desired_runtime(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> None:
        """恢复一个缺失的 desired=running runtime，并记录结果和退避。"""

        runtime_id = workflow_app_runtime.workflow_runtime_id
        failure_context: tuple[WorkflowAppRuntime, str] | None = None
        recovery_worker_instance_id: str | None = None
        try:
            if self._stopping.is_set():
                return
            with self._resolve_runtime_lifecycle_lock(runtime_id):
                recovery_target = self._get_recoverable_runtime_target(runtime_id)
                if recovery_target is None:
                    return
                latest, expected_fingerprint = recovery_target
                failure_context = recovery_target
                expected_revision_id = latest.active_revision_id
                if expected_revision_id is None:
                    return
                expected_generation = latest.revision_generation
                stored_worker_instance_id = latest.worker_instance_id
                runtime_state = self._start_runtime(
                    latest,
                    workflow_runtime_revision_id=expected_revision_id,
                    runtime_generation=expected_generation,
                    expected_snapshot_fingerprint=expected_fingerprint,
                )
                recovery_worker_instance_id = runtime_state.instance_id
                if self._stopping.is_set():
                    self._stop_runtime(runtime_id)
                    return
                with self._lock:
                    recovered_handle = self._handles.get(runtime_id)
                persisted = self._persist_runtime_state_event(
                    workflow_runtime_id=runtime_id,
                    runtime_state=runtime_state,
                    event_type="runtime.recovered",
                    message="workflow app runtime 已按持久化期望状态恢复",
                    expected_revision_id=expected_revision_id,
                    expected_generation=expected_generation,
                    expected_snapshot_fingerprint=expected_fingerprint,
                    expected_worker_instance_id=stored_worker_instance_id,
                    source_worker_instance_id=runtime_state.instance_id,
                    source_handle=recovered_handle,
                )
                if not persisted:
                    self._stop_runtime(runtime_id)
                    return
            with self._lock:
                self._recovery_failures.pop(runtime_id, None)
                self._recovery_next_attempt_at.pop(runtime_id, None)
        except Exception as error:  # noqa: BLE001 - 单个 runtime 失败不能终止恢复线程
            if recovery_worker_instance_id is not None:
                try:
                    with self._resolve_runtime_lifecycle_lock(runtime_id):
                        with self._lock:
                            failed_handle = self._handles.get(runtime_id)
                        if (
                            failed_handle is not None
                            and failed_handle.worker_instance_id
                            == recovery_worker_instance_id
                        ):
                            self._stop_runtime(runtime_id)
                except Exception:  # noqa: BLE001 - 恢复失败后的清理不能覆盖原错误
                    pass
            with self._lock:
                failure_count = self._recovery_failures.get(runtime_id, 0) + 1
                self._recovery_failures[runtime_id] = failure_count
                self._recovery_next_attempt_at[runtime_id] = monotonic() + min(
                    60.0,
                    float(2 ** min(failure_count - 1, 6)),
                )
            if failure_context is None:
                return
            failed_runtime, expected_fingerprint = failure_context
            expected_revision_id = failed_runtime.active_revision_id
            if expected_revision_id is None:
                return
            runtime_state = build_synthetic_runtime_state(
                previous_state=None,
                observed_state="failed",
                last_error=f"workflow runtime 自动恢复失败: {error}",
            )
            runtime_state = replace(
                runtime_state,
                instance_id=failed_runtime.worker_instance_id,
                loaded_snapshot_fingerprint=expected_fingerprint,
            )
            try:
                self._persist_runtime_state_event(
                    workflow_runtime_id=runtime_id,
                    runtime_state=runtime_state,
                    event_type="runtime.recovery_failed",
                    message="workflow app runtime 自动恢复失败，将按退避策略重试",
                    expected_revision_id=expected_revision_id,
                    expected_generation=failed_runtime.revision_generation,
                    expected_snapshot_fingerprint=expected_fingerprint,
                    expected_worker_instance_id=(failed_runtime.worker_instance_id),
                    source_worker_instance_id=failed_runtime.worker_instance_id,
                )
            except Exception:  # noqa: BLE001 - 数据库暂时不可用时保持恢复循环存活
                pass
        finally:
            with self._lock:
                self._recovery_threads.pop(runtime_id, None)

    def _get_recoverable_runtime_target(
        self,
        workflow_runtime_id: str,
    ) -> tuple[WorkflowAppRuntime, str] | None:
        """读取仍可恢复的 active revision 及其不可变 snapshot 指纹。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            if (
                workflow_app_runtime is None
                or workflow_app_runtime.desired_state != "running"
                or workflow_app_runtime.active_revision_id is None
                or workflow_app_runtime.desired_revision_id
                != workflow_app_runtime.active_revision_id
            ):
                return None
            revision = unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                workflow_app_runtime.active_revision_id
            )
            if (
                revision is None
                or revision.state != "active"
                or revision.generation != workflow_app_runtime.revision_generation
            ):
                return None
            return (
                workflow_app_runtime,
                revision.expected_snapshot_fingerprint,
            )
        finally:
            unit_of_work.close()

    def _persist_runtime_state_event(
        self,
        *,
        workflow_runtime_id: str,
        runtime_state: WorkflowRuntimeWorkerState,
        event_type: str,
        message: str,
        expected_revision_id: str | None,
        expected_generation: int,
        expected_snapshot_fingerprint: str | None,
        expected_worker_instance_id: str | None,
        source_worker_instance_id: str | None,
        source_handle: _WorkflowRuntimeProcessHandle | None = None,
    ) -> bool:
        """仅在 revision 与 worker epoch 未变化时回写后台状态和事件。"""

        if expected_revision_id is None or expected_snapshot_fingerprint is None:
            return False
        if (
            runtime_state.instance_id is not None
            and runtime_state.instance_id != source_worker_instance_id
        ):
            return False
        if (
            runtime_state.loaded_snapshot_fingerprint is not None
            and runtime_state.loaded_snapshot_fingerprint
            != expected_snapshot_fingerprint
        ):
            return False
        if source_handle is not None:
            with self._lock:
                current_handle = self._handles.get(workflow_runtime_id)
            if (
                current_handle is not source_handle
                or source_handle.workflow_runtime_revision_id != expected_revision_id
                or source_handle.runtime_generation != expected_generation
                or source_handle.expected_snapshot_fingerprint
                != expected_snapshot_fingerprint
                or source_handle.worker_instance_id != source_worker_instance_id
            ):
                return False

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        updated_runtime: WorkflowAppRuntime | None = None
        try:
            workflow_app_runtime = (
                unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_runtime_id
                )
            )
            if (
                workflow_app_runtime is None
                or workflow_app_runtime.desired_state != "running"
                or workflow_app_runtime.active_revision_id != expected_revision_id
                or workflow_app_runtime.desired_revision_id != expected_revision_id
                or workflow_app_runtime.revision_generation != expected_generation
                or workflow_app_runtime.worker_instance_id
                != expected_worker_instance_id
            ):
                return False
            revision = unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                expected_revision_id
            )
            if (
                revision is None
                or revision.state != "active"
                or revision.generation != expected_generation
                or revision.expected_snapshot_fingerprint
                != expected_snapshot_fingerprint
            ):
                return False
            updated_runtime = replace(
                workflow_app_runtime,
                observed_state=runtime_state.observed_state,
                updated_at=now_isoformat(),
                heartbeat_at=runtime_state.heartbeat_at,
                worker_instance_id=source_worker_instance_id,
                worker_process_id=runtime_state.process_id,
                loaded_snapshot_fingerprint=expected_snapshot_fingerprint,
                last_error=runtime_state.last_error,
                health_summary=dict(runtime_state.health_summary),
            )
            updated = unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                updated_runtime,
                expected_generation=expected_generation,
                expected_revision_id=expected_revision_id,
                expected_worker_instance_id=expected_worker_instance_id,
                expected_desired_state="running",
            )
            if not updated:
                unit_of_work.rollback()
                return False
            unit_of_work.commit()
        finally:
            unit_of_work.close()
        if updated_runtime is None:
            return False
        append_workflow_app_runtime_event(
            dataset_storage=self.dataset_storage,
            service_event_bus=self.service_event_bus,
            session_factory=self.session_factory,
            workflow_app_runtime=updated_runtime,
            event_type=event_type,
            message=message,
        )
        return True

    def _resolve_runtime_start_timeout_seconds(
        self, *, has_model_loaders: bool = False
    ) -> float:
        """返回 runtime worker 启动阶段的控制面等待超时。"""

        configured_timeout_seconds = float(
            self.settings.deployment_process_supervisor.startup_timeout_seconds
        )
        if not has_model_loaders:
            return max(configured_timeout_seconds, 5.0)
        model_startup_timeout_seconds = float(
            self.settings.workflow_runtime.model_startup_timeout_seconds
        )
        return max(
            configured_timeout_seconds,
            model_startup_timeout_seconds,
            5.0,
        )

    def _resolve_runtime_lifecycle_lock(self, workflow_runtime_id: str) -> RLock:
        """按 runtime id 返回有界分段生命周期锁。"""

        lock_index = hash(workflow_runtime_id) % len(self._runtime_lifecycle_locks)
        return self._runtime_lifecycle_locks[lock_index]

    @contextmanager
    def runtime_lifecycle_guard(self, workflow_runtime_id: str) -> Iterator[None]:
        """串行化同一 Runtime 的控制面动作和调用句柄接管。"""

        with self._resolve_runtime_lifecycle_lock(workflow_runtime_id):
            yield

    def reserve_sync_admission(
        self,
        workflow_runtime_id: str,
        workflow_run_id: str,
    ) -> None:
        """登记一条轻量同步调用占用，仅用于关闭 Runtime 删除窗口。"""

        with self._lock:
            self._sync_admissions.setdefault(workflow_runtime_id, set()).add(
                workflow_run_id
            )

    def release_sync_admission(
        self,
        workflow_runtime_id: str,
        workflow_run_id: str,
    ) -> None:
        """释放同步调用占用；重复释放保持幂等。"""

        with self._lock:
            workflow_run_ids = self._sync_admissions.get(workflow_runtime_id)
            if workflow_run_ids is None:
                return
            workflow_run_ids.discard(workflow_run_id)
            if not workflow_run_ids:
                self._sync_admissions.pop(workflow_runtime_id, None)

    def list_sync_admission_run_ids(
        self,
        workflow_runtime_id: str,
    ) -> tuple[str, ...]:
        """读取当前同步调用占用，不参与执行调度或排队。"""

        with self._lock:
            return tuple(sorted(self._sync_admissions.get(workflow_runtime_id, ())))

    @staticmethod
    def _validate_handle_identity(
        handle: _WorkflowRuntimeProcessHandle,
        *,
        workflow_app_runtime: WorkflowAppRuntime,
        expected_revision_id: str | None,
        expected_generation: int | None,
        expected_snapshot_fingerprint: str | None,
    ) -> None:
        """拒绝把固定来源的请求发送到另一 revision 的 worker。"""

        revision_id = expected_revision_id or workflow_app_runtime.active_revision_id
        generation = (
            workflow_app_runtime.revision_generation
            if expected_generation is None
            else expected_generation
        )
        fingerprint = (
            expected_snapshot_fingerprint
            or workflow_app_runtime.loaded_snapshot_fingerprint
        )
        worker_instance_id = workflow_app_runtime.worker_instance_id
        if (
            revision_id is None
            or handle.workflow_runtime_revision_id != revision_id
            or handle.runtime_generation != generation
            or fingerprint is None
            or handle.expected_snapshot_fingerprint != fingerprint
            or not worker_instance_id
            or handle.worker_instance_id != worker_instance_id
        ):
            raise ResourceConflictError(
                "WorkflowAppRuntime worker 身份与请求固定来源不一致",
                details={
                    "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                    "expected_revision_id": revision_id,
                    "actual_revision_id": handle.workflow_runtime_revision_id,
                    "expected_generation": generation,
                    "actual_generation": handle.runtime_generation,
                    "expected_snapshot_fingerprint": fingerprint,
                    "actual_snapshot_fingerprint": (
                        handle.expected_snapshot_fingerprint
                    ),
                    "expected_worker_instance_id": worker_instance_id,
                    "actual_worker_instance_id": handle.worker_instance_id,
                },
            )

    @staticmethod
    def _validate_worker_response_identity(
        message: dict[str, object],
        handle: _WorkflowRuntimeProcessHandle,
    ) -> None:
        """确认响应来自本次接管的 worker epoch 和固定 revision。"""

        response_revision_id = message.get("workflow_runtime_revision_id")
        response_generation = message.get("runtime_generation")
        response_fingerprint = message.get("snapshot_fingerprint")
        response_instance_id = message.get("worker_instance_id")
        if (
            handle.expected_snapshot_fingerprint is None
            and isinstance(response_fingerprint, str)
            and response_fingerprint
        ):
            # 未显式提供预期指纹的内部兼容调用，只允许同一 revision/generation/
            # worker epoch 的首条消息固定一次，后续消息仍执行严格相等校验。
            handle.expected_snapshot_fingerprint = response_fingerprint
        if (
            response_revision_id != handle.workflow_runtime_revision_id
            or response_generation != handle.runtime_generation
            or response_fingerprint != handle.expected_snapshot_fingerprint
            or response_instance_id != handle.worker_instance_id
        ):
            raise ServiceConfigurationError(
                "workflow runtime worker 响应身份不匹配",
                details={
                    "expected_revision_id": handle.workflow_runtime_revision_id,
                    "actual_revision_id": response_revision_id,
                    "expected_generation": handle.runtime_generation,
                    "actual_generation": response_generation,
                    "expected_worker_instance_id": handle.worker_instance_id,
                    "actual_worker_instance_id": response_instance_id,
                },
            )

    def _snapshot_has_model_loaders(self, template_snapshot_object_key: str) -> bool:
        """快速判断固定 snapshot 是否包含 Load Checkpoint 节点。"""

        try:
            payload = self.dataset_storage.read_json(template_snapshot_object_key)
        except Exception:
            return False
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(nodes, list):
            return False
        return any(
            isinstance(node, dict)
            and node.get("enabled", True) is not False
            and str(node.get("node_type_id") or "").endswith(".load-checkpoint")
            for node in nodes
        )

    def _resolve_local_buffer_broker_event_channel(
        self,
    ) -> LocalBufferBrokerEventChannel | None:
        """读取当前 broker 事件通道。"""

        if self.local_buffer_broker_event_channel_provider is None:
            return None
        return self.local_buffer_broker_event_channel_provider()

    def _build_published_inference_gateway_channel(
        self,
    ) -> PublishedInferenceGatewayEventChannel | None:
        """为一个 runtime worker 创建 PublishedInferenceGateway 事件通道。"""

        if self.published_inference_gateway is None:
            return None
        from backend.service.application.deployments import (
            PublishedInferenceGatewayEventChannel,
        )

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
        from backend.service.application.deployments import (
            PublishedInferenceGatewayDispatcher,
        )

        return PublishedInferenceGatewayDispatcher(
            channel=channel, gateway=self.published_inference_gateway
        )


def _elapsed_ms(started_at: float) -> float:
    """把 monotonic 起点转换为毫秒耗时。"""

    return round((monotonic() - started_at) * 1000.0, 3)
