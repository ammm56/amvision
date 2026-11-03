"""恢复线程不能排在显式启动后再次占用已就绪 Runtime 的实时准入。"""

from threading import Event, Lock, RLock, Thread
from types import MethodType, SimpleNamespace

from backend.service.application.workflows.worker.manager import WorkflowRuntimeWorkerManager


def manager(*, available):
    """使用真实 guard/recovery 方法，禁止无效恢复继续读取或写入发布状态。"""
    lock = RLock()
    instance = SimpleNamespace(
        _stopping=Event(), _lock=Lock(), _recovery_threads={"runtime": object()},
        _recovery_failures={}, _recovery_next_attempt_at={},
        _resolve_runtime_lifecycle_lock=lambda _: lock,
        is_runtime_available=lambda _: available,
    )
    instance.runtime_lifecycle_guard = MethodType(WorkflowRuntimeWorkerManager.runtime_lifecycle_guard, instance)

    def unexpected(_):
        raise AssertionError("不应继续重复恢复或读取发布")

    instance._get_recoverable_runtime_target = unexpected
    return instance, lock


def test_recovery_does_not_wait_behind_explicit_start():
    """启动持锁时恢复立即退出；不排队，不改变失败/退避或就绪状态。"""
    instance, lock = manager(available=False)
    done = Event()

    def recover():
        WorkflowRuntimeWorkerManager._recover_desired_runtime(instance, SimpleNamespace(workflow_runtime_id="runtime"))
        done.set()

    thread = Thread(target=recover)
    try:
        with lock:
            thread.start()
            assert done.wait(2)
    finally:
        thread.join(2)
    assert not thread.is_alive()
    assert instance._recovery_threads == {}
    assert instance._recovery_failures == instance._recovery_next_attempt_at == {}


def test_recovery_rechecks_worker_after_scheduling():
    """扫描时缺失、执行时已存在的 worker 不重复发布 recovered 事件。"""
    instance, _ = manager(available=True)
    WorkflowRuntimeWorkerManager._recover_desired_runtime(instance, SimpleNamespace(workflow_runtime_id="runtime"))
    assert instance._recovery_threads == {}
    assert instance._recovery_failures == instance._recovery_next_attempt_at == {}
