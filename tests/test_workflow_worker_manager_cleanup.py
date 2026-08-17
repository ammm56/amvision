"""Workflow runtime worker handle 清理所有权测试。"""

from __future__ import annotations

from threading import Event, Lock, Thread
from types import SimpleNamespace

import backend.service.application.workflows.worker.manager as manager_module


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
