"""后台线程停止确认与恢复准入的跨平台回归。"""

from threading import Event

import pytest

from backend.service.application.errors import InvalidRequestError, OperationTimeoutError
from backend.service.application.runtime.deployment.deployment_runtime_reconciler import (
    DeploymentRuntimeReconciler,
)
from backend.service.application.tasks.queue_outbox import (
    QueueOutboxDispatcher,
    QueueOutboxDispatcherSettings,
)
from backend.service.settings import BackendServiceDeploymentRuntimeReconcilerConfig
from backend.bootstrap.core import RuntimeLifecycle


@pytest.fixture(params=["outbox", "reconciler"])
def component(request):
    """使用真实线程和事件隔离数据库、设备及文件队列。"""
    if request.param == "outbox":
        instance = QueueOutboxDispatcher(
            session_factory=None, queue_backend=None,
            settings=QueueOutboxDispatcherSettings(shutdown_timeout_seconds=0.1),
        )
        method = "dispatch_once"
    else:
        instance = DeploymentRuntimeReconciler(
            state_service=None, lookup_service=None, bindings_by_task_type={},
            settings=BackendServiceDeploymentRuntimeReconcilerConfig(
                reconcile_interval_seconds=0.01,
            ),
        )
        method = "reconcile_once"
    entered, release = Event(), Event()

    def block():
        """模拟不可在 Python 安全点内中断的在途操作。"""
        entered.set()
        assert release.wait(15)
        return 0

    setattr(instance, method, block)
    yield instance, entered, release
    release.set()
    instance.stop()


def test_stop_timeout_preserves_thread_and_rejects_restart(component):
    """停止失败不报告成功，旧线程退出后也须先完成 stop 确认。"""
    instance, entered, release = component
    instance.start()
    assert entered.wait(5)
    thread = instance._thread
    with pytest.raises(OperationTimeoutError):
        instance.stop()
    assert thread.is_alive()
    assert instance._thread is thread
    with pytest.raises(InvalidRequestError):
        instance.start()
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    with pytest.raises(InvalidRequestError):
        instance.start()
    instance.stop()
    assert instance._thread is None
    entered.clear()
    instance.start()
    assert entered.wait(5)
    assert instance._thread is not thread
    instance.stop()


def test_repeated_start_does_not_replace_running_thread(component):
    """正常重复启动幂等，不产生第二个后台执行者。"""
    instance, entered, release = component
    instance.start()
    assert entered.wait(5)
    thread = instance._thread
    instance.start()
    assert instance._thread is thread
    release.set()
    instance.stop()
    instance.stop()


def test_thread_start_failure_does_not_leave_unjoinable_thread(component, monkeypatch):
    """OS 启动失败仍能正常停止，且不保留未启动的 Thread。"""
    instance, _, _ = component

    def fail_start(_thread):
        """在 Thread 创建后模拟 OS 拒绝启动。"""
        raise RuntimeError("thread launch failed")

    monkeypatch.setattr("threading.Thread.start", fail_start)
    with pytest.raises(RuntimeError, match="thread launch failed"):
        instance.start()
    instance.stop()
    assert instance._thread is None


def test_runtime_lifecycle_failed_stop_retains_restart_fence():
    """资源容器不允许复用；失败的停止允许重试，成功 drain 不重复执行。"""
    lifecycle = RuntimeLifecycle()
    with lifecycle.starting() as begin:
        assert begin
    with lifecycle.starting() as begin:
        assert not begin
    with pytest.raises(OperationTimeoutError):
        with lifecycle.stopping():
            raise OperationTimeoutError()
    with pytest.raises(RuntimeError, match="停止"):
        with lifecycle.starting():
            pytest.fail("不能再次启动")
    with lifecycle.stopping(final=False) as drain:
        assert drain
    with lifecycle.stopping() as stop:
        assert stop
        with lifecycle.stopping(final=False) as drain:
            assert not drain
    with lifecycle.stopping() as stop:
        assert not stop


def test_reconciler_does_not_recover_after_stopped_dependency_probe():
    """依赖探测中到达的停止请求不能继续领取部署恢复工作。"""
    reconciler = DeploymentRuntimeReconciler(
        state_service=None, lookup_service=None, bindings_by_task_type={},
        settings=BackendServiceDeploymentRuntimeReconcilerConfig(),
    )

    def dependency():
        """在读取依赖时模拟停止已到达。"""
        reconciler._stop_event.set()
        return {"ready": True}

    reconciler.dependency_readiness_provider = dependency
    reconciler.reconcile_once()
    assert reconciler.readiness_snapshot()["ready"] is False


def test_deployment_monitor_timeout_preserves_dependencies_and_restart_fence(tmp_path, monkeypatch):
    """监控线程可能仍在恢复模型，停止超时不能释放设备或重新启动。"""
    from backend.service.application.runtime.deployment.deployment_process_supervisor import DeploymentProcessSupervisor
    from backend.service.settings import BackendServiceDeploymentProcessSupervisorConfig

    instance = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path), runtime_mode="sync",
        settings=BackendServiceDeploymentProcessSupervisorConfig(shutdown_timeout_seconds=0.1),
    )
    entered, release = Event(), Event()
    released = []

    def monitor():
        entered.set()
        assert release.wait(15)

    monkeypatch.setattr(instance, "_run_monitor_loop", monitor)
    monkeypatch.setattr(instance.cpu_device_resource_manager, "release_owner", lambda _: released.append(True))
    try:
        instance.start()
        assert entered.wait(5)
        thread = instance._monitor_thread
        with pytest.raises(OperationTimeoutError):
            instance.stop()
        assert not released
        with pytest.raises(InvalidRequestError):
            instance.start()
        release.set()
        thread.join(5)
        with pytest.raises(InvalidRequestError):
            instance.start()
        with pytest.raises(InvalidRequestError):
            instance._start_process_with_capacity_locked(None)
        instance.stop()
        assert released == [True]
        instance.start()
        assert instance._monitor_thread is not thread
    finally:
        release.set()
        instance.stop()


@pytest.mark.parametrize("kind", ["mailbox", "status"])
def test_daemon_adapter_stop_timeout_retains_owner(tmp_path, monkeypatch, kind):
    """真实 dispatcher 未退出时，adapter 不得释放 mmap owner 或允许再次启动。"""
    from backend.service.infrastructure.ipc.inference_mailbox import InferenceLocalMmapServer
    from backend.service.infrastructure.ipc.service_status_channel import InferenceStatusPublisher

    if kind == "mailbox":
        instance = InferenceLocalMmapServer(buffers_root=tmp_path, service_id="test", request_handler=lambda _: {})
        method, resource = "_run_loop", "_server"
    else:
        instance = InferenceStatusPublisher(str(tmp_path), lambda: {})
        method, resource = "_run", "_publisher"
    entered, release = Event(), Event()

    def block():
        entered.set()
        assert release.wait(20)

    monkeypatch.setattr(instance, method, block)
    try:
        instance.start()
        assert entered.wait(5)
        thread, owner = instance._thread, getattr(instance, resource)
        with pytest.raises(OperationTimeoutError):
            instance.stop()
        assert instance._thread is thread and getattr(instance, resource) is owner
        with pytest.raises(InvalidRequestError):
            instance.start()
        release.set()
        thread.join(5)
        with pytest.raises(InvalidRequestError):
            instance.start()
        instance.stop()
        assert getattr(instance, resource) is None
    finally:
        release.set()
        instance.stop()
