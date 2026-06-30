"""后台任务管理器。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Thread
from typing import Protocol


class BackgroundTaskConsumer(Protocol):
    """描述可被后台任务管理器调度的消费者。"""

    def run_once(self) -> bool:
        """执行一次任务消费。

        返回：
        - 当实际处理了一条任务时返回 True；否则返回 False。
        """

        ...


@dataclass(frozen=True)
class BackgroundTaskManagerConfig:
    """描述后台任务管理器配置。

    字段：
    - max_concurrent_tasks：最大并发任务数。
    - poll_interval_seconds：空闲轮询间隔秒数。
    """

    max_concurrent_tasks: int = 1
    poll_interval_seconds: float = 1.0


class BackgroundTaskManager:
    """按固定并发上限调度后台任务消费者。"""

    def __init__(
        self,
        *,
        consumers: tuple[BackgroundTaskConsumer, ...],
        config: BackgroundTaskManagerConfig,
    ) -> None:
        """初始化后台任务管理器。

        参数：
        - consumers：要调度的后台任务消费者列表。
        - config：后台任务管理配置。
        """

        self.consumers = consumers
        self.config = config

    def run_available_tasks(self) -> int:
        """并发处理当前可领取的任务。

        返回：
        - 当前批次成功领取并执行的任务数量。
        """

        max_workers = max(1, self.config.max_concurrent_tasks)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._run_next_available_task) for _ in range(max_workers)]
            return sum(1 for future in futures if future.result())

    def run_forever(self, stop_event: Event | None = None) -> None:
        """持续轮询并执行后台任务。

        参数：
        - stop_event：可选的停止事件；触发后退出循环。
        """

        event = stop_event or Event()
        max_workers = max(1, self.config.max_concurrent_tasks)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._run_worker_loop, event)
                for _ in range(max_workers)
            ]
            while not event.is_set():
                for future in futures:
                    if future.done():
                        error = future.exception()
                        if error is not None:
                            event.set()
                            raise error
                event.wait(0.2)

    def _run_next_available_task(self) -> bool:
        """尝试从已注册消费者中执行下一条可用任务。

        返回：
        - 当某个消费者实际处理了一条任务时返回 True；否则返回 False。
        """

        for consumer in self.consumers:
            if consumer.run_once():
                return True

        return False

    def _run_worker_loop(self, stop_event: Event) -> None:
        """持续占用一个 worker 槽位并轮询可执行任务。

        说明：
        - 旧实现按批次提交 future，并等待整批 future 完成。
        - 当一个长训练任务占住批次时，后续新入队任务无法被空闲槽继续领取。
        - 这里让每个槽位常驻轮询，保证后续提交的任务能被空闲槽及时消费。
        """

        while not stop_event.is_set():
            processed = self._run_next_available_task()
            if not processed:
                stop_event.wait(max(0.1, self.config.poll_interval_seconds))


class HostedBackgroundTaskManager:
    """在后台线程中托管 BackgroundTaskManager。

    字段：
    - task_manager：被托管的后台任务管理器。
    - thread_name：后台线程名称。
    """

    def __init__(
        self,
        *,
        task_manager: BackgroundTaskManager,
        thread_name: str = "background-task-manager",
    ) -> None:
        """初始化后台任务管理器宿主。

        参数：
        - task_manager：被托管的后台任务管理器。
        - thread_name：后台线程名称。
        """

        self.task_manager = task_manager
        self.thread_name = thread_name
        self._stop_event = Event()
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        """返回后台线程是否正在运行。

        返回：
        - 当后台线程存在且仍在运行时返回 True；否则返回 False。
        """

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动后台任务管理器线程。"""

        if self.is_running:
            return

        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name=self.thread_name,
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, join_timeout_seconds: float = 5.0) -> None:
        """停止后台任务管理器线程。

        参数：
        - join_timeout_seconds：等待线程退出的最长秒数。
        """

        thread = self._thread
        if thread is None:
            return

        self._stop_event.set()
        thread.join(timeout=max(0.1, join_timeout_seconds))
        if not thread.is_alive():
            self._thread = None

    def _run(self) -> None:
        """执行后台线程主体。"""

        try:
            self.task_manager.run_forever(stop_event=self._stop_event)
        finally:
            self._thread = None
