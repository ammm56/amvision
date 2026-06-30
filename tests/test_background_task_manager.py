"""后台任务管理器调度行为测试。"""

from __future__ import annotations

from threading import Event, Thread

from backend.workers.task_manager import (
    BackgroundTaskManager,
    BackgroundTaskManagerConfig,
)


class _BlockingConsumer:
    """模拟占用一个 worker 槽位的长任务消费者。"""

    def __init__(self) -> None:
        """初始化长任务状态。"""

        self.started = Event()
        self.release = Event()
        self._claimed = False

    def run_once(self) -> bool:
        """只领取一次任务，并阻塞到测试释放。"""

        if self._claimed:
            return False
        self._claimed = True
        self.started.set()
        self.release.wait(timeout=5)
        return True


class _DelayedConsumer:
    """模拟长任务运行期间稍后入队的第二个任务。"""

    def __init__(self) -> None:
        """初始化延迟任务状态。"""

        self.available = Event()
        self.consumed = Event()

    def run_once(self) -> bool:
        """当任务可用后只消费一次。"""

        if not self.available.is_set() or self.consumed.is_set():
            return False
        self.consumed.set()
        return True


def test_background_task_manager_keeps_idle_slots_polling() -> None:
    """长任务占用一个槽位时，空闲槽仍应继续领取后续入队任务。"""

    blocking_consumer = _BlockingConsumer()
    delayed_consumer = _DelayedConsumer()
    stop_event = Event()
    task_manager = BackgroundTaskManager(
        consumers=(blocking_consumer, delayed_consumer),
        config=BackgroundTaskManagerConfig(
            max_concurrent_tasks=2,
            poll_interval_seconds=0.02,
        ),
    )

    worker_thread = Thread(
        target=task_manager.run_forever,
        kwargs={"stop_event": stop_event},
        daemon=True,
    )
    worker_thread.start()

    try:
        assert blocking_consumer.started.wait(timeout=1)

        delayed_consumer.available.set()

        assert delayed_consumer.consumed.wait(timeout=1)
    finally:
        stop_event.set()
        blocking_consumer.release.set()
        worker_thread.join(timeout=1)

    assert not worker_thread.is_alive()
