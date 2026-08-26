"""Workflow runtime worker handle 清理所有权测试。"""

from __future__ import annotations

from dataclasses import replace
from threading import Event, Lock, RLock, Thread
from types import SimpleNamespace

import backend.service.application.workflows.worker.manager as manager_module
import pytest

from backend.service.application.errors import (
    OperationTimeoutError,
    ResourceConflictError,
    ServiceConfigurationError,
    WorkflowRuntimeBusyError,
)
from backend.service.application.workflows.worker.messages import (
    WorkflowRuntimeAsyncRunCallbacks,
)
from backend.service.application.workflows.worker.health import (
    WorkflowRuntimeWorkerState,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
)


class _FakeQueue:
    """记录 Queue 关闭次数的线程安全测试替身。"""

    def __init__(self) -> None:
        self.close_count = 0
        self.join_count = 0
        self._lock = Lock()

    def close(self) -> None:
        """记录一次 close。"""

        with self._lock:
            self.close_count += 1

    def join_thread(self) -> None:
        """记录一次 join_thread。"""

        with self._lock:
            self.join_count += 1


def test_node_pack_timeout_latches_first_reason_and_earliest_force_deadline() -> None:
    """并行节点 timeout 只固化首因，但更早 grace 仍可提前整代回收。"""

    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._monitor_wake_event = Event()  # noqa: SLF001
    cancellation_event = Event()
    handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id="runtime-1",
        process=SimpleNamespace(pid=321, is_alive=lambda: True),
        request_queue=_FakeQueue(),
        response_queue=_FakeQueue(),
        run_cancellation_event=cancellation_event,
        runtime_generation=3,
    )
    handle.active_run_request_ids["run-1"] = "request-1"
    now = manager_module.monotonic()
    common_identity = {
        "message_type": "node-started",
        "workflow_run_id": "run-1",
        "node_pack_id": "pack-1",
    }
    first_invocation_id = "1" * 32
    second_invocation_id = "2" * 32

    worker_manager._handle_node_lifecycle_message(  # noqa: SLF001
        handle=handle,
        message={
            **common_identity,
            "node_invocation_id": first_invocation_id,
            "node_id": "node-first",
            "deadline_monotonic": now - 0.2,
            "kill_grace_seconds": 1.0,
        },
    )
    assert (
        worker_manager._monitor_node_pack_timeouts(  # noqa: SLF001
            handle=handle,
            now=now,
        )
        is None
    )
    assert cancellation_event.is_set()

    worker_manager._handle_node_lifecycle_message(  # noqa: SLF001
        handle=handle,
        message={
            **common_identity,
            "node_invocation_id": second_invocation_id,
            "node_id": "node-second",
            "deadline_monotonic": now - 0.1,
            "kill_grace_seconds": 0.0,
        },
    )
    timeout_state = worker_manager._monitor_node_pack_timeouts(  # noqa: SLF001
        handle=handle,
        now=now,
    )

    assert timeout_state is not None
    assert timeout_state.node_invocation_id == first_invocation_id
    assert timeout_state.node_id == "node-first"
    assert timeout_state.force_kill_deadline_monotonic == pytest.approx(now - 0.1)

    worker_manager._handle_node_lifecycle_message(  # noqa: SLF001
        handle=handle,
        message={
            "message_type": "node-ended",
            "workflow_run_id": "run-1",
            "node_invocation_id": first_invocation_id,
            "node_id": "node-first",
            "outcome": "cancelled",
        },
    )
    assert handle.node_timeout_states["run-1"].node_id == "node-first"


def test_execution_token_is_real_gate_and_release_is_idempotent() -> None:
    """统一 token 直接持有真实 request lock，reject 满载且释放幂等。"""

    runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-token",
        generation=1,
        fingerprint="fingerprint-token",
    )
    worker_manager = _build_token_worker_manager(runtime)

    token = worker_manager.acquire_execution_token(
        workflow_app_runtime=runtime,
        workflow_run_id="run-1",
        timeout_seconds=1.0,
        acquisition_mode="reject",
        expected_revision_id=runtime.active_revision_id,
        expected_generation=runtime.revision_generation,
        expected_snapshot_fingerprint=runtime.loaded_snapshot_fingerprint,
    )

    assert worker_manager.list_execution_token_run_ids(
        runtime.workflow_runtime_id
    ) == ("run-1",)
    with pytest.raises(WorkflowRuntimeBusyError):
        worker_manager.acquire_execution_token(
            workflow_app_runtime=runtime,
            workflow_run_id="run-2",
            timeout_seconds=1.0,
            acquisition_mode="reject",
            expected_revision_id=runtime.active_revision_id,
            expected_generation=runtime.revision_generation,
            expected_snapshot_fingerprint=runtime.loaded_snapshot_fingerprint,
        )

    assert worker_manager.release_execution_token(token) is True
    assert worker_manager.release_execution_token(token) is False
    assert worker_manager.list_execution_token_run_ids(runtime.workflow_runtime_id) == ()


def test_execution_token_waits_on_same_runtime_but_different_runtime_is_independent() -> (
    None
):
    """wait 模式只等待同一 Runtime；不同 Runtime 可同时取得真实执行权。"""

    first_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-first",
        generation=1,
        fingerprint="fingerprint-first",
    )
    second_runtime = replace(
        _build_test_workflow_runtime(
            revision_id="workflow-runtime-revision-second",
            generation=1,
            fingerprint="fingerprint-second",
        ),
        workflow_runtime_id="workflow-runtime-second",
    )
    worker_manager = _build_token_worker_manager(first_runtime)
    _add_token_runtime_handle(worker_manager, second_runtime)
    first_token = _acquire_test_token(worker_manager, first_runtime, "run-first")
    second_token = _acquire_test_token(worker_manager, second_runtime, "run-second")
    wait_started = Event()
    wait_completed = Event()
    waited_tokens: list[manager_module.WorkflowRuntimeExecutionToken] = []

    def acquire_waiting_token() -> None:
        wait_started.set()
        waited_tokens.append(
            worker_manager.acquire_execution_token(
                workflow_app_runtime=first_runtime,
                workflow_run_id="run-waiting",
                timeout_seconds=2.0,
                acquisition_mode="wait",
                expected_revision_id=first_runtime.active_revision_id,
                expected_generation=first_runtime.revision_generation,
                expected_snapshot_fingerprint=(
                    first_runtime.loaded_snapshot_fingerprint
                ),
            )
        )
        wait_completed.set()

    thread = Thread(target=acquire_waiting_token)
    thread.start()
    assert wait_started.wait(timeout=1.0)
    assert wait_completed.wait(timeout=0.05) is False
    assert worker_manager.release_execution_token(first_token) is True
    assert wait_completed.wait(timeout=1.0)
    thread.join(timeout=1.0)

    assert thread.is_alive() is False
    assert waited_tokens[0].workflow_run_id == "run-waiting"
    assert worker_manager.release_execution_token(waited_tokens[0]) is True
    assert worker_manager.release_execution_token(second_token) is True


def test_previous_generation_token_cannot_release_new_handle_token() -> None:
    """旧 worker token 的迟到释放只影响旧 handle，不会释放新代 request lock。"""

    old_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-old",
        generation=1,
        fingerprint="fingerprint-old",
    )
    worker_manager = _build_token_worker_manager(old_runtime)
    old_token = _acquire_test_token(worker_manager, old_runtime, "run-old")
    new_runtime = replace(
        old_runtime,
        active_revision_id="workflow-runtime-revision-new",
        desired_revision_id="workflow-runtime-revision-new",
        revision_generation=2,
        loaded_snapshot_fingerprint="fingerprint-new",
        worker_instance_id="worker-2",
    )
    _add_token_runtime_handle(worker_manager, new_runtime)
    new_token = _acquire_test_token(worker_manager, new_runtime, "run-new")

    assert worker_manager.release_execution_token(old_token) is True
    with pytest.raises(WorkflowRuntimeBusyError):
        _acquire_test_token(worker_manager, new_runtime, "run-must-stay-busy")
    assert worker_manager.list_execution_token_run_ids(
        new_runtime.workflow_runtime_id
    ) == ("run-new",)
    assert worker_manager.release_execution_token(new_token) is True


def test_sync_invoke_rejects_stale_worker_epoch_before_dispatch() -> None:
    """同步调用不能把旧 epoch 固定来源发给同版本新 worker。"""

    workflow_app_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-1",
        generation=1,
        fingerprint="fingerprint-1",
    )
    worker_manager = _build_epoch_mismatch_worker_manager(workflow_app_runtime)

    with pytest.raises(ResourceConflictError) as exc_info:
        worker_manager.invoke_runtime(
            workflow_app_runtime=workflow_app_runtime,
            workflow_run_id="workflow-run-sync-stale-epoch",
            input_bindings={},
            execution_metadata={},
            timeout_seconds=60,
            expected_revision_id="workflow-runtime-revision-1",
            expected_generation=1,
            expected_snapshot_fingerprint="fingerprint-1",
        )

    assert exc_info.value.details["expected_worker_instance_id"] == "worker-1"
    assert (
        exc_info.value.details["actual_worker_instance_id"]
        == "worker-recovered-same-version"
    )


def test_sync_invoke_timeout_includes_request_lock_wait() -> None:
    """同步调用的总 timeout 必须包含等待前一个请求释放执行槽位的时间。"""

    workflow_app_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-lock-timeout",
        generation=1,
        fingerprint="fingerprint-lock-timeout",
    )
    request_lock = Lock()
    request_lock.acquire()
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (RLock(),)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {  # noqa: SLF001
        workflow_app_runtime.workflow_runtime_id: SimpleNamespace(
            process=SimpleNamespace(is_alive=lambda: True),
            workflow_runtime_revision_id=workflow_app_runtime.active_revision_id,
            runtime_generation=workflow_app_runtime.revision_generation,
            expected_snapshot_fingerprint=(
                workflow_app_runtime.loaded_snapshot_fingerprint
            ),
            worker_instance_id=workflow_app_runtime.worker_instance_id,
            request_lock=request_lock,
        )
    }

    try:
        with pytest.raises(OperationTimeoutError) as exc_info:
            worker_manager.invoke_runtime(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id="workflow-run-lock-timeout",
                input_bindings={},
                execution_metadata={},
                timeout_seconds=0.05,  # type: ignore[arg-type]
                expected_revision_id=workflow_app_runtime.active_revision_id,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_snapshot_fingerprint=(
                    workflow_app_runtime.loaded_snapshot_fingerprint
                ),
            )
    finally:
        request_lock.release()

    assert exc_info.value.details["timeout_phase"] == "request_lock"
    assert request_lock.acquire(blocking=False) is True
    request_lock.release()


def test_sync_invoke_timeout_includes_runtime_lifecycle_lock_wait() -> None:
    """同步调用总 timeout 也必须覆盖 Runtime 启停或切版锁等待。"""

    workflow_app_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-lifecycle-timeout",
        generation=1,
        fingerprint="fingerprint-lifecycle-timeout",
    )
    lifecycle_lock = Lock()
    lifecycle_lock.acquire()
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (lifecycle_lock,)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {}  # noqa: SLF001

    try:
        with pytest.raises(OperationTimeoutError) as exc_info:
            worker_manager.invoke_runtime(
                workflow_app_runtime=workflow_app_runtime,
                workflow_run_id="workflow-run-lifecycle-timeout",
                input_bindings={},
                execution_metadata={},
                timeout_seconds=0.05,  # type: ignore[arg-type]
                expected_revision_id=workflow_app_runtime.active_revision_id,
                expected_generation=workflow_app_runtime.revision_generation,
                expected_snapshot_fingerprint=(
                    workflow_app_runtime.loaded_snapshot_fingerprint
                ),
            )
    finally:
        lifecycle_lock.release()

    assert exc_info.value.details["timeout_phase"] == "runtime_lifecycle_lock"


def test_sync_invoke_releases_request_lock_when_identity_changes_after_wait() -> None:
    """获得执行槽位后的版本复核失败不能永久占用 request lock。"""

    workflow_app_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-identity-race",
        generation=1,
        fingerprint="fingerprint-identity-race",
    )
    request_lock = Lock()
    handle = SimpleNamespace(
        process=SimpleNamespace(is_alive=lambda: True),
        workflow_runtime_revision_id=workflow_app_runtime.active_revision_id,
        runtime_generation=workflow_app_runtime.revision_generation,
        expected_snapshot_fingerprint=(
            workflow_app_runtime.loaded_snapshot_fingerprint
        ),
        worker_instance_id=workflow_app_runtime.worker_instance_id,
        request_lock=request_lock,
    )
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (RLock(),)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {  # noqa: SLF001
        workflow_app_runtime.workflow_runtime_id: handle
    }
    validation_count = 0

    def validate_identity(*_args: object, **_kwargs: object) -> None:
        nonlocal validation_count
        validation_count += 1
        if validation_count == 2:
            raise ResourceConflictError("worker identity changed")

    worker_manager._validate_handle_identity = validate_identity  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(ResourceConflictError, match="identity changed"):
        worker_manager.invoke_runtime(
            workflow_app_runtime=workflow_app_runtime,
            workflow_run_id="workflow-run-identity-race",
            input_bindings={},
            execution_metadata={},
            timeout_seconds=1,
            expected_revision_id=workflow_app_runtime.active_revision_id,
            expected_generation=workflow_app_runtime.revision_generation,
            expected_snapshot_fingerprint=(
                workflow_app_runtime.loaded_snapshot_fingerprint
            ),
        )

    assert request_lock.acquire(blocking=False) is True
    request_lock.release()


def test_manager_start_waits_for_desired_runtime_recovery_before_monitor() -> None:
    """启动返回前必须完成首轮 Runtime 恢复，供随后 Trigger 启动形成屏障。"""

    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager.settings = SimpleNamespace(
        workflow_runtime=SimpleNamespace(model_startup_parallelism=2)
    )
    worker_manager._stopping = Event()  # noqa: SLF001
    worker_manager._monitor_stop_event = Event()  # noqa: SLF001
    worker_manager._monitor_wake_event = Event()  # noqa: SLF001
    worker_manager._monitor_thread = None  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {}  # noqa: SLF001
    worker_manager._recovery_threads = {}  # noqa: SLF001
    recovery_started = Event()
    allow_recovery_finish = Event()
    monitor_started = Event()
    runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-startup",
        generation=1,
        fingerprint="fingerprint-startup",
    )
    worker_manager._load_recoverable_desired_runtimes = lambda: (runtime,)  # type: ignore[method-assign]  # noqa: SLF001

    def recover(_runtime: WorkflowAppRuntime) -> None:
        recovery_started.set()
        assert allow_recovery_finish.wait(timeout=2.0)

    worker_manager._recover_desired_runtime = recover  # type: ignore[method-assign]  # noqa: SLF001
    worker_manager._run_monitor_loop = monitor_started.set  # type: ignore[method-assign]  # noqa: SLF001
    start_thread = Thread(target=worker_manager.start)

    start_thread.start()
    assert recovery_started.wait(timeout=1.0)
    assert worker_manager._monitor_thread is None  # noqa: SLF001
    assert monitor_started.is_set() is False

    allow_recovery_finish.set()
    start_thread.join(timeout=2.0)

    assert start_thread.is_alive() is False
    assert monitor_started.wait(timeout=1.0)


def test_async_invoke_rejects_stale_worker_epoch_before_dispatch() -> None:
    """异步后台调用复用同一 epoch 栅栏，并确定回写 ResourceConflict。"""

    workflow_app_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-1",
        generation=1,
        fingerprint="fingerprint-1",
    )
    worker_manager = _build_epoch_mismatch_worker_manager(workflow_app_runtime)
    failed_errors: list[ResourceConflictError] = []
    async_handle = manager_module._WorkflowRuntimeAsyncRunHandle(  # noqa: SLF001
        workflow_app_runtime=workflow_app_runtime,
        workflow_run_id="workflow-run-async-stale-epoch",
        input_bindings={},
        execution_metadata={},
        timeout_seconds=60,
        expected_revision_id="workflow-runtime-revision-1",
        expected_generation=1,
        expected_snapshot_fingerprint="fingerprint-1",
        callbacks=WorkflowRuntimeAsyncRunCallbacks(
            on_started=lambda: None,
            on_completed=lambda _result: None,
            on_cancelled=lambda _state: None,
            on_failed=lambda error: failed_errors.append(error),
            on_timed_out=lambda _error: None,
        ),
    )
    worker_manager._async_runs[async_handle.workflow_run_id] = async_handle  # noqa: SLF001

    worker_manager._run_async_workflow(async_handle)  # noqa: SLF001

    assert async_handle.completion_event.is_set()
    assert len(failed_errors) == 1
    error = failed_errors[0]
    assert error.details["expected_worker_instance_id"] == "worker-1"
    assert error.details["actual_worker_instance_id"] == (
        "worker-recovered-same-version"
    )


def test_runtime_handle_cleanup_is_idempotent_across_competing_owners(
    monkeypatch,
) -> None:
    """monitor 与生命周期调用方竞争时只能关闭一次 handle 资源。"""

    request_queue = _FakeQueue()
    response_queue = _FakeQueue()
    pending_event = Event()
    dispatcher = SimpleNamespace(stop_count=0)
    dispatcher.stop = lambda: setattr(
        dispatcher,
        "stop_count",
        dispatcher.stop_count + 1,
    )
    channel_close_counts = {"buffer": 0, "gateway": 0}
    monkeypatch.setattr(
        manager_module.worker_process,
        "close_local_buffer_broker_channel",
        lambda _channel: channel_close_counts.__setitem__(
            "buffer",
            channel_close_counts["buffer"] + 1,
        ),
    )
    monkeypatch.setattr(
        manager_module.worker_process,
        "close_published_inference_gateway_channel",
        lambda _channel: channel_close_counts.__setitem__(
            "gateway",
            channel_close_counts["gateway"] + 1,
        ),
    )
    handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id="workflow-runtime-cleanup-race",
        process=SimpleNamespace(is_alive=lambda: False),
        request_queue=request_queue,
        response_queue=response_queue,
        local_buffer_broker_event_channel=SimpleNamespace(),
        published_inference_gateway_channel=SimpleNamespace(),
        published_inference_gateway_dispatcher=dispatcher,
        pending_responses={
            "pending-1": SimpleNamespace(
                error_message=None,
                event=pending_event,
            )
        },
    )
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    errors: list[BaseException] = []

    def cleanup() -> None:
        """在线程中执行清理并保留异常。"""

        try:
            worker_manager._cleanup_handle(handle)  # noqa: SLF001
        except BaseException as error:  # pragma: no cover - 失败时用于断言
            errors.append(error)

    threads = tuple(Thread(target=cleanup) for _ in range(2))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)
    worker_manager._cleanup_handle(handle)  # noqa: SLF001

    assert errors == []
    assert all(thread.is_alive() is False for thread in threads)
    assert handle.expected_shutdown is True
    assert handle.cleanup_completed is True
    assert handle.pending_responses == {}
    assert pending_event.is_set() is True
    assert request_queue.close_count == 1
    assert request_queue.join_count == 1
    assert response_queue.close_count == 1
    assert response_queue.join_count == 1
    assert dispatcher.stop_count == 1
    assert channel_close_counts == {"buffer": 1, "gateway": 1}


def test_get_runtime_health_does_not_remove_replacement_handle() -> None:
    """health 检查旧死进程期间发生接管时必须返回并保留新 handle。"""

    workflow_runtime_id = "workflow-runtime-health-replacement"
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (RLock(),)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {}  # noqa: SLF001
    new_state = WorkflowRuntimeWorkerState(
        observed_state="running",
        instance_id="worker-epoch-new",
    )
    new_handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id=workflow_runtime_id,
        process=SimpleNamespace(is_alive=lambda: True),
        request_queue=SimpleNamespace(),
        response_queue=SimpleNamespace(),
        worker_instance_id="worker-epoch-new",
        latest_runtime_state=new_state,
    )

    def replace_then_report_dead() -> bool:
        """在 health 完成 old handle 活性检查前模拟新 worker 接管。"""

        with worker_manager._lock:  # noqa: SLF001
            worker_manager._handles[workflow_runtime_id] = new_handle  # noqa: SLF001
        return False

    old_handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id=workflow_runtime_id,
        process=SimpleNamespace(is_alive=replace_then_report_dead),
        request_queue=SimpleNamespace(),
        response_queue=SimpleNamespace(),
        worker_instance_id="worker-epoch-old",
    )
    worker_manager._handles[workflow_runtime_id] = old_handle  # noqa: SLF001
    cleaned_handles: list[object] = []
    worker_manager._cleanup_handle = cleaned_handles.append  # noqa: SLF001

    runtime_state = worker_manager.get_runtime_health(workflow_runtime_id)

    assert runtime_state is new_state
    assert worker_manager._handles[workflow_runtime_id] is new_handle  # noqa: SLF001
    assert cleaned_handles == [old_handle]


def test_runtime_health_waits_for_startup_ready_publication() -> None:
    """health 必须等待 lifecycle startup 栅栏，并只读取 ready 后发布的 handle。"""

    workflow_runtime_id = "workflow-runtime-health-startup-fence"
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (RLock(),)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {}  # noqa: SLF001
    startup_entered = Event()
    allow_ready_publication = Event()
    health_completed = Event()
    health_states: list[WorkflowRuntimeWorkerState] = []
    ready_state = WorkflowRuntimeWorkerState(
        observed_state="running",
        instance_id="worker-ready",
    )
    ready_handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id=workflow_runtime_id,
        process=SimpleNamespace(is_alive=lambda: True),
        request_queue=SimpleNamespace(),
        response_queue=SimpleNamespace(),
        worker_instance_id="worker-ready",
        latest_runtime_state=ready_state,
    )
    request_state_calls: list[object] = []
    worker_manager._request_runtime_state = request_state_calls.append  # type: ignore[method-assign]  # noqa: SLF001

    def publish_ready_handle() -> None:
        """模拟 _start_runtime 在 lifecycle 临界区末尾发布 ready handle。"""

        with worker_manager._resolve_runtime_lifecycle_lock(  # noqa: SLF001
            workflow_runtime_id
        ):
            startup_entered.set()
            assert allow_ready_publication.wait(timeout=2.0)
            with worker_manager._lock:  # noqa: SLF001
                worker_manager._handles[workflow_runtime_id] = ready_handle  # noqa: SLF001

    def read_health() -> None:
        """读取 health 并记录完成时点。"""

        health_states.append(worker_manager.get_runtime_health(workflow_runtime_id))
        health_completed.set()

    startup_thread = Thread(target=publish_ready_handle)
    health_thread = Thread(target=read_health)
    startup_thread.start()
    assert startup_entered.wait(timeout=1.0)
    health_thread.start()
    assert health_completed.wait(timeout=0.1) is False

    allow_ready_publication.set()
    startup_thread.join(timeout=2.0)
    health_thread.join(timeout=2.0)

    assert startup_thread.is_alive() is False
    assert health_thread.is_alive() is False
    assert health_states == [ready_state]
    assert request_state_calls == []


def test_failed_old_handle_termination_does_not_remove_replacement_handle() -> None:
    """同步调用延迟清理旧 handle 时不能删除已接管的新 worker。"""

    workflow_runtime_id = "workflow-runtime-terminate-replacement"
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._monitor_wake_event = Event()  # noqa: SLF001
    new_handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id=workflow_runtime_id,
        process=SimpleNamespace(is_alive=lambda: True),
        request_queue=SimpleNamespace(),
        response_queue=SimpleNamespace(),
        worker_instance_id="worker-epoch-new",
    )
    old_handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id=workflow_runtime_id,
        process=SimpleNamespace(is_alive=lambda: False),
        request_queue=SimpleNamespace(),
        response_queue=SimpleNamespace(),
        worker_instance_id="worker-epoch-old",
    )
    worker_manager._handles = {workflow_runtime_id: new_handle}  # noqa: SLF001
    cleaned_handles: list[object] = []
    worker_manager._cleanup_handle = cleaned_handles.append  # noqa: SLF001

    worker_manager._terminate_failed_handle(  # noqa: SLF001
        workflow_runtime_id=workflow_runtime_id,
        handle=old_handle,
    )

    assert worker_manager._handles[workflow_runtime_id] is new_handle  # noqa: SLF001
    assert cleaned_handles == [old_handle]
    assert worker_manager._monitor_wake_event.is_set()  # noqa: SLF001


def test_worker_response_identity_rejects_previous_worker_epoch() -> None:
    """相同 revision/generation 的旧进程响应也必须被 worker epoch 拒绝。"""

    handle = manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
        workflow_runtime_id="workflow-runtime-identity",
        process=SimpleNamespace(is_alive=lambda: True),
        request_queue=SimpleNamespace(),
        response_queue=SimpleNamespace(),
        workflow_runtime_revision_id="workflow-runtime-revision-2",
        runtime_generation=2,
        expected_snapshot_fingerprint="fingerprint-2",
        worker_instance_id="worker-epoch-2",
    )

    with pytest.raises(ServiceConfigurationError, match="响应身份不匹配"):
        manager_module.WorkflowRuntimeWorkerManager._validate_worker_response_identity(  # noqa: SLF001
            {
                "workflow_runtime_revision_id": "workflow-runtime-revision-2",
                "runtime_generation": 2,
                "snapshot_fingerprint": "fingerprint-2",
                "worker_instance_id": "worker-epoch-1",
            },
            handle,
        )


def test_cancelled_async_run_does_not_restart_replaced_revision() -> None:
    """旧异步任务取消完成后不能把已切换的 Runtime 拉回旧 revision。"""

    old_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-1",
        generation=1,
        fingerprint="fingerprint-1",
    )
    current_runtime = _build_test_workflow_runtime(
        revision_id="workflow-runtime-revision-2",
        generation=2,
        fingerprint="fingerprint-2",
    )
    callbacks = WorkflowRuntimeAsyncRunCallbacks(
        on_started=lambda: None,
        on_completed=lambda _result: None,
        on_cancelled=lambda _state: None,
        on_failed=lambda _error: None,
        on_timed_out=lambda _error: None,
    )
    async_handle = manager_module._WorkflowRuntimeAsyncRunHandle(  # noqa: SLF001
        workflow_app_runtime=old_runtime,
        workflow_run_id="workflow-run-old",
        input_bindings={},
        execution_metadata={},
        timeout_seconds=10,
        expected_revision_id=old_runtime.active_revision_id,
        expected_generation=old_runtime.revision_generation,
        expected_snapshot_fingerprint="fingerprint-1",
        callbacks=callbacks,
    )
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (manager_module.RLock(),)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {}  # noqa: SLF001
    worker_manager._get_recoverable_runtime_target = (  # noqa: SLF001
        lambda _runtime_id: (current_runtime, "fingerprint-2")
    )
    start_calls: list[str] = []
    worker_manager._start_runtime = (  # noqa: SLF001
        lambda runtime, **_kwargs: start_calls.append(runtime.workflow_runtime_id)
    )

    worker_manager._recover_cancelled_async_runtime(async_handle)  # noqa: SLF001

    assert start_calls == []


def test_previous_worker_epoch_cannot_persist_background_state(
    monkeypatch,
) -> None:
    """新 worker 接管 DB 后，旧 heartbeat/failure 必须静默丢弃。"""

    current_runtime = replace(
        _build_test_workflow_runtime(
            revision_id="workflow-runtime-revision-2",
            generation=2,
            fingerprint="fingerprint-2",
        ),
        worker_instance_id="worker-epoch-new",
    )
    repository = SimpleNamespace(
        get_workflow_app_runtime=lambda _runtime_id: current_runtime,
    )
    unit_of_work = SimpleNamespace(
        workflow_runtime=repository,
        close=lambda: None,
    )
    monkeypatch.setattr(
        manager_module,
        "SqlAlchemyUnitOfWork",
        lambda _session: unit_of_work,
    )
    appended_events: list[str] = []
    monkeypatch.setattr(
        manager_module,
        "append_workflow_app_runtime_event",
        lambda **_kwargs: appended_events.append("event"),
    )
    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager.session_factory = SimpleNamespace(
        create_session=lambda: SimpleNamespace()
    )
    worker_manager.dataset_storage = SimpleNamespace()
    worker_manager.service_event_bus = None
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._handles = {}  # noqa: SLF001

    persisted = worker_manager._persist_runtime_state_event(  # noqa: SLF001
        workflow_runtime_id=current_runtime.workflow_runtime_id,
        runtime_state=WorkflowRuntimeWorkerState(
            observed_state="failed",
            instance_id="worker-epoch-old",
            loaded_snapshot_fingerprint="fingerprint-2",
            last_error="旧 worker 延迟上报",
        ),
        event_type="runtime.failed",
        message="旧 worker 失败",
        expected_revision_id=current_runtime.active_revision_id,
        expected_generation=current_runtime.revision_generation,
        expected_snapshot_fingerprint="fingerprint-2",
        expected_worker_instance_id="worker-epoch-old",
        source_worker_instance_id="worker-epoch-old",
    )

    assert persisted is False
    assert appended_events == []


def _build_test_workflow_runtime(
    *,
    revision_id: str,
    generation: int,
    fingerprint: str,
) -> WorkflowAppRuntime:
    """构造固定到指定 revision 的测试 Runtime。"""

    return WorkflowAppRuntime(
        workflow_runtime_id="workflow-runtime-versioned",
        project_id="project-1",
        application_id="workflow-app-1",
        display_name="Versioned Runtime",
        application_snapshot_object_key="workflow/apps/app.json",
        template_snapshot_object_key="workflow/templates/graph.json",
        active_revision_id=revision_id,
        desired_revision_id=revision_id,
        revision_generation=generation,
        desired_state="running",
        observed_state="running",
        worker_instance_id=f"worker-{generation}",
        loaded_snapshot_fingerprint=fingerprint,
    )


def _build_token_worker_manager(
    workflow_app_runtime: WorkflowAppRuntime,
) -> manager_module.WorkflowRuntimeWorkerManager:
    """构造只用于 execution token 状态机的 manager。"""

    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (RLock(),)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._execution_tokens = {}  # noqa: SLF001
    worker_manager._execution_token_ids_by_runtime = {}  # noqa: SLF001
    worker_manager._handles = {}  # noqa: SLF001
    _add_token_runtime_handle(worker_manager, workflow_app_runtime)
    return worker_manager


def _add_token_runtime_handle(
    worker_manager: manager_module.WorkflowRuntimeWorkerManager,
    workflow_app_runtime: WorkflowAppRuntime,
) -> None:
    """为 token 测试安装一代可运行 handle。"""

    worker_manager._handles[workflow_app_runtime.workflow_runtime_id] = (  # noqa: SLF001
        manager_module._WorkflowRuntimeProcessHandle(  # noqa: SLF001
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            process=SimpleNamespace(pid=321, is_alive=lambda: True),
            request_queue=_FakeQueue(),
            response_queue=_FakeQueue(),
            workflow_runtime_revision_id=workflow_app_runtime.active_revision_id,
            runtime_generation=workflow_app_runtime.revision_generation,
            expected_snapshot_fingerprint=(
                workflow_app_runtime.loaded_snapshot_fingerprint
            ),
            worker_instance_id=workflow_app_runtime.worker_instance_id,
        )
    )


def _acquire_test_token(
    worker_manager: manager_module.WorkflowRuntimeWorkerManager,
    workflow_app_runtime: WorkflowAppRuntime,
    workflow_run_id: str,
) -> manager_module.WorkflowRuntimeExecutionToken:
    """以 reject 模式取得测试 Runtime token。"""

    return worker_manager.acquire_execution_token(
        workflow_app_runtime=workflow_app_runtime,
        workflow_run_id=workflow_run_id,
        timeout_seconds=1.0,
        acquisition_mode="reject",
        expected_revision_id=workflow_app_runtime.active_revision_id,
        expected_generation=workflow_app_runtime.revision_generation,
        expected_snapshot_fingerprint=(
            workflow_app_runtime.loaded_snapshot_fingerprint
        ),
    )


def _build_epoch_mismatch_worker_manager(
    workflow_app_runtime: WorkflowAppRuntime,
) -> manager_module.WorkflowRuntimeWorkerManager:
    """构造版本相同但 worker epoch 已更换的 manager。"""

    worker_manager = object.__new__(manager_module.WorkflowRuntimeWorkerManager)
    worker_manager._runtime_lifecycle_locks = (RLock(),)  # noqa: SLF001
    worker_manager._lock = Lock()  # noqa: SLF001
    worker_manager._async_runs = {}  # noqa: SLF001
    worker_manager._handles = {  # noqa: SLF001
        workflow_app_runtime.workflow_runtime_id: SimpleNamespace(
            process=SimpleNamespace(is_alive=lambda: True),
            workflow_runtime_revision_id=workflow_app_runtime.active_revision_id,
            runtime_generation=workflow_app_runtime.revision_generation,
            expected_snapshot_fingerprint=(
                workflow_app_runtime.loaded_snapshot_fingerprint
            ),
            worker_instance_id="worker-recovered-same-version",
        )
    }
    return worker_manager
