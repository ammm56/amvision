"""实时准入和恢复扫描的受控跨平台边界测试。"""

import gc
from threading import Event, Thread
from types import SimpleNamespace
from weakref import ref

import pytest

from backend.service.application.errors import InvalidRequestError, OperationCancelledError, OperationTimeoutError, WorkflowRuntimeBusyError
from backend.service.application.workflows.runtime_service import WorkflowRuntimeService
from backend.service.application.workflows.worker import manager as manager_module
from backend.service.settings import BackendServiceSettings


@pytest.fixture
def manager():
    """构造正式 manager，但不启动进程或访问数据库。"""
    return manager_module.WorkflowRuntimeWorkerManager(
        settings=BackendServiceSettings(),
        session_factory=SimpleNamespace(service_event_bus=None),
        dataset_storage=None,
    )


@pytest.mark.parametrize("blocked_kind", ["monitor", "recovery"])
def test_manager_stop_requires_thread_exit_before_dependency_close(manager, monkeypatch, blocked_kind):
    """停止超时保留依赖和恢复栅栏，线程稍后退出也必须再次确认停止。"""
    entered, release = Event(), Event()
    closed = []

    def blocked():
        entered.set()
        assert release.wait(15)

    thread = Thread(target=blocked)
    if blocked_kind == "monitor":
        manager._monitor_thread = thread
    else:
        manager._recovery_threads["blocked"] = thread
    monkeypatch.setattr(manager, "_close_cleanup_local_buffer_client", lambda: closed.append(True))
    monkeypatch.setattr(manager, "_recover_desired_runtimes_before_monitor", lambda: None)
    thread.start()
    try:
        assert entered.wait(2)
        with pytest.raises(OperationTimeoutError):
            manager.stop()
        assert not closed and manager._stopping.is_set()
        with pytest.raises(InvalidRequestError):
            manager.start()
        release.set()
        thread.join(2)
        with pytest.raises(InvalidRequestError):
            manager.start()
        manager.stop()
        assert closed == [True]
        manager.start()
    finally:
        release.set()
        thread.join(2)
        manager.stop()


def test_manager_failed_group_stop_is_not_reported_as_success(manager, monkeypatch):
    """整组回收失败必须向上抛出，不释放 Broker 或恢复准入。"""
    closed = []
    manager._handles["failed"] = object()
    monkeypatch.setattr(manager, "_close_cleanup_local_buffer_client", lambda: closed.append(True))

    def failed(_):
        raise OperationTimeoutError("controlled group stop failure")

    monkeypatch.setattr(manager, "stop_runtime", failed)
    with pytest.raises(OperationTimeoutError):
        manager.stop()
    assert not closed
    with pytest.raises(InvalidRequestError):
        manager.start()
    manager._handles.clear()
    manager.stop()


def test_manager_async_completion_is_required_before_dependency_close(manager, monkeypatch):
    """异步完成回调仍在使用依赖时，停止必须失败并保留依赖。"""
    handle = SimpleNamespace(cancel_event=Event(), completion_event=Event())
    manager._async_runs["pending"] = handle
    closed = []
    monkeypatch.setattr(manager, "_close_cleanup_local_buffer_client", lambda: closed.append(True))
    try:
        with pytest.raises(OperationTimeoutError):
            manager.stop()
        assert handle.cancel_event.is_set() and not closed
    finally:
        handle.completion_event.set()
        manager._async_runs.clear()
        manager.stop()


def test_stop_during_startup_keeps_restart_fence(manager, monkeypatch):
    """首轮恢复仍阻塞时停止有界失败；启动退出后必须完成显式清理。"""
    entered, release = Event(), Event()
    errors = []
    closed = []

    def recover():
        entered.set()
        assert release.wait(10)

    def start():
        try:
            manager.start()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(manager, "_recover_desired_runtimes_before_monitor", recover)
    monkeypatch.setattr(manager, "_close_cleanup_local_buffer_client", lambda: closed.append(True))
    thread = Thread(target=start)
    thread.start()
    try:
        assert entered.wait(2)
        with pytest.raises(OperationTimeoutError):
            manager.stop()
        assert not closed
        release.set()
        thread.join(2)
        assert len(errors) == 1 and isinstance(errors[0], OperationCancelledError)
        assert manager._monitor_thread is None
        with pytest.raises(InvalidRequestError):
            manager.start()
        manager.stop()
        assert closed == [True]
    finally:
        release.set()
        thread.join(2)
        manager.stop()


def test_cleanup_close_failure_retains_client_and_restart_fence(manager):
    """close 失败后保留原引用以供重试，不能吞错后允许恢复。"""
    def fail():
        raise OSError("controlled close failure")

    client = SimpleNamespace(close=fail)
    manager._cleanup_local_buffer_client = client
    with pytest.raises(OSError):
        manager.stop()
    assert manager._cleanup_local_buffer_client is client
    with pytest.raises(InvalidRequestError):
        manager.start()
    client.close = lambda: None
    manager.stop()
    assert manager._cleanup_local_buffer_client is None


def test_stopped_manager_rejects_sync_admission_before_state_access(manager):
    """已停止 manager 不能在新调用中重新取得执行 token。"""
    manager.stop()
    with pytest.raises(InvalidRequestError):
        manager.acquire_execution_token(workflow_app_runtime=None, workflow_run_id="new",
                                        timeout_seconds=1, acquisition_mode="reject")


def test_sync_reject_does_not_wait_for_outer_lifecycle_guard(manager):
    """停止持锁时，服务层必须在读取状态或创建 Run 前拒绝。"""
    service = object.__new__(WorkflowRuntimeService)
    service.worker_manager = manager
    admitted = []
    service._admit_sync_workflow_run = lambda *a, **kw: admitted.append(True)
    entered, release, completed = Event(), Event(), Event()
    errors = []

    def control():
        """以独立线程模拟持有生命周期锁的停止操作。"""
        with manager.runtime_lifecycle_guard("runtime-a"):
            entered.set()
            assert release.wait(10)

    def invoke():
        """调用真实服务准入入口并记录失败。"""
        try:
            service.admit_sync_workflow_run("runtime-a", None, created_by=None)
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()

    controller, caller = Thread(target=control), Thread(target=invoke)
    controller.start()
    try:
        assert entered.wait(5)
        caller.start()
        assert completed.wait(1), "reject 被外层生命周期锁阻塞"
        assert len(errors) == 1 and isinstance(errors[0], WorkflowRuntimeBusyError)
        assert errors[0].details["busy_phase"] == "runtime_lifecycle"
        assert not admitted
    finally:
        release.set()
        controller.join(5)
        if caller.ident is not None:
            caller.join(5)
    assert not controller.is_alive() and not caller.is_alive()


def test_different_runtime_locks_do_not_collide(manager):
    """不同 Runtime 不得因 hash 分段而互相拒绝或等待。"""
    first = "runtime-a"
    second = next(
        f"runtime-{index}"
        for index in range(10000)
        if f"runtime-{index}" != first and hash(f"runtime-{index}") % 64 == hash(first) % 64
    )
    first_lock = manager._resolve_runtime_lifecycle_lock(first)
    assert first_lock is manager._resolve_runtime_lifecycle_lock(first)
    assert first_lock is not manager._resolve_runtime_lifecycle_lock(second)


def test_lifecycle_locks_are_reentrant_and_retired_without_history(manager):
    """持有或等待中的锁保持唯一，无使用者后不会积累历史 ID。"""
    observed = []
    with manager.runtime_lifecycle_guard("active"):
        lock = manager._resolve_runtime_lifecycle_lock("active")
        weak_lock = ref(lock)
        with manager.runtime_lifecycle_guard("active", acquisition_mode="reject"):
            assert manager._resolve_runtime_lifecycle_lock("active") is lock
        contender = Thread(target=lambda: observed.append(manager._resolve_runtime_lifecycle_lock("active")))
        contender.start()
        contender.join(5)
        assert not contender.is_alive() and observed == [lock]
        del lock
        observed.clear()
        gc.collect()
        assert weak_lock() is not None
    gc.collect()
    assert weak_lock() is None
    for index in range(1000):
        with manager.runtime_lifecycle_guard(f"retired-{index}"):
            pass
    assert len(manager._runtime_lifecycle_locks) == 0


def test_lifecycle_guard_releases_after_error_and_rejects_invalid_mode(manager):
    """异常不泄漏控制锁，非法准入模式不隐式转为阻塞。"""
    with pytest.raises(ValueError):
        with manager.runtime_lifecycle_guard("runtime-a"):
            raise ValueError("controlled failure")
    with manager.runtime_lifecycle_guard("runtime-a", acquisition_mode="reject"):
        pass
    with pytest.raises(InvalidRequestError):
        with manager.runtime_lifecycle_guard("runtime-a", acquisition_mode="unknown"):
            pytest.fail("invalid mode entered")


def test_node_wakes_do_not_amplify_database_recovery_scan(manager, monkeypatch):
    """一秒内一千次节点唤醒仍只按原有半秒周期扫描数据库。"""
    clock = [0.0]
    scans = []

    class NodeWakes:
        """无 wall-clock 休眠地模拟高频普通节点唤醒。"""

        def clear(self):
            pass

        def wait(self, timeout):
            assert timeout <= 0.5
            clock[0] += 0.001
            if clock[0] >= 1.001:
                manager._monitor_stop_event.set()

    monkeypatch.setattr(manager_module, "monotonic", lambda: clock[0])
    manager._monitor_wake_event = NodeWakes()
    manager._schedule_desired_runtime_recoveries = lambda: scans.append(clock[0])
    manager._run_monitor_loop()
    assert len(scans) == 3
    assert scans == pytest.approx([0.0, 0.5, 1.0], abs=0.001)


def test_recovery_during_scan_is_preserved_without_waiting_for_period(manager, monkeypatch):
    """普通唤醒不扫描，实际故障及扫描期间的新故障均立即处理。"""
    clock = [0.0]
    scans = []

    class RecoveryWakes:
        """以固定时序提供恢复和退出事件。"""

        def clear(self):
            pass

        def wait(self, timeout):
            clock[0] = round(clock[0] + 0.01, 2)
            if clock[0] == 0.1:
                manager._recovery_scan_requested.set()
            if clock[0] == 0.12:
                manager._monitor_stop_event.set()

    def scan():
        """第二轮扫描尚未结束时又有一个旧进程组完成回收。"""
        scans.append(clock[0])
        if clock[0] == 0.1:
            manager._recovery_scan_requested.set()

    monkeypatch.setattr(manager_module, "monotonic", lambda: clock[0])
    manager._monitor_wake_event = RecoveryWakes()
    manager._schedule_desired_runtime_recoveries = scan
    manager._run_monitor_loop()
    assert scans == [0.0, 0.1, 0.11]


def test_scan_failure_retains_periodic_retry(manager, monkeypatch):
    """数据库错误不能中止 monitor，也不能变成节点频率的失败重试。"""
    clock = [0.0]
    scans = []

    class Wakes:
        """注入连续唤醒并在周期重试后退出。"""

        def clear(self):
            pass

        def wait(self, timeout):
            clock[0] += 0.01
            if clock[0] > 0.51:
                manager._monitor_stop_event.set()

    def scan():
        scans.append(clock[0])
        raise OSError("database unavailable")

    monkeypatch.setattr(manager_module, "monotonic", lambda: clock[0])
    manager._monitor_wake_event = Wakes()
    manager._schedule_desired_runtime_recoveries = scan
    manager._run_monitor_loop()
    assert scans == pytest.approx([0.0, 0.5])
