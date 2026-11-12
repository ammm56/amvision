"""启动故障必须传递首因、有界恢复，不能误伤执行态或跨版本状态。"""

from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from backend.service.application.errors import ResourceConflictError, ServiceError
from backend.service.application.workflows.worker.manager import (
    WorkflowRuntimeWorkerManager,
    _WorkflowRuntimeProcessHandle,
)
from backend.service.application.workflows.worker.startup import (
    build_recovery_failure,
    build_startup_failure,
    read_startup_failure,
    recovery_blocked,
)


def runtime():
    """同一发布代的最小恢复快照。"""
    return SimpleNamespace(active_revision_id="revision", revision_generation=3, health_summary={})


@pytest.mark.parametrize("error", [
    FileNotFoundError(2, "文件不存在", "D:/missing/snapshot.json"),
    PermissionError(13, "无法访问文件", "D:/denied/snapshot.json"),
    ResourceConflictError("节点已变化，请重新发布", details={"requires_republish": True, "node_type_ids": ["core.rule.check-limits"]}),
])
def test_permanent_startup_cause_survives_worker_roundtrip(error):
    """跨进程还原后仍保留路径、原因和不应重试标志。"""
    restored = read_startup_failure(build_startup_failure(error, {}))
    record = build_recovery_failure(restored, runtime())
    assert record["attempt"] == 1
    assert record["retryable"] is False
    assert record["error"]["message"] == str(error)
    assert record["error"]["details"]["error_type"] == type(error).__name__
    if isinstance(error, ServiceError):
        assert record["error"]["details"]["node_type_ids"] == ["core.rule.check-limits"]
        assert record["action"] == "republish"


def test_transient_recovery_is_bounded_and_revision_or_manual_start_resets_it():
    """三次失败后持久化阻止；切版和显式启动清空状态后可再次恢复。"""
    value = runtime()
    for attempt in range(1, 4):
        record = build_recovery_failure(TimeoutError("startup timeout"), value)
        assert record["attempt"] == attempt
        value.health_summary = {"recovery": record}
        assert recovery_blocked(value) is (attempt == 3)
    # 新 manager 从数据库读取同样数据，仍然不能从零开始反复启动。
    reloaded = SimpleNamespace(**vars(value))
    assert recovery_blocked(reloaded)
    reloaded.revision_generation += 1
    assert not recovery_blocked(reloaded)
    value.health_summary = {}
    assert not recovery_blocked(value)
    assert build_recovery_failure(TimeoutError(), value)["attempt"] == 1


def test_exited_process_queued_failure_is_consumed_before_exitcode_fallback():
    """真实响应线程即使看到子进程已退出，也先消费具体错误；旧代消息无效。"""
    manager = object.__new__(WorkflowRuntimeWorkerManager)
    queue = Queue()
    handle = _WorkflowRuntimeProcessHandle(
        workflow_runtime_id="runtime", process=SimpleNamespace(is_alive=lambda: False, exitcode=1),
        request_queue=Queue(), response_queue=queue, run_cancellation_event=Event(),
        workflow_runtime_revision_id="revision", runtime_generation=3,
        expected_snapshot_fingerprint="sha256:expected", worker_instance_id="worker",
    )
    identity = dict(workflow_runtime_id="runtime", workflow_runtime_revision_id="revision",
                    runtime_generation=3, expected_snapshot_fingerprint="sha256:expected", worker_instance_id="worker")
    queue.put(build_startup_failure(ValueError("不能显示旧 worker 的错误"), identity | {"worker_instance_id": "old"}))
    queue.put(build_startup_failure(FileNotFoundError(2, "文件不存在", "missing.json"), identity))
    thread = Thread(target=manager._run_response_loop, args=(handle,))
    handle.response_thread = thread
    thread.start()
    try:
        with pytest.raises(ServiceError, match="missing.json") as caught:
            manager._wait_for_startup_state(handle, timeout_seconds=2)
        assert caught.value.details["permanent"] is True
    finally:
        handle.response_stop_event.set()
        thread.join(2)
    assert not thread.is_alive()
