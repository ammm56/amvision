"""训练任务队列 lease 心跳。"""

from __future__ import annotations

import logging
from threading import Event, Lock, Thread

from backend.queue import QueueBackend, QueueMessage


LOGGER = logging.getLogger(__name__)
DEFAULT_LEASE_TIMEOUT_SECONDS = 86400.0
TRAINING_LEASE_TIMEOUT_SECONDS = 900.0
MAX_HEARTBEAT_INTERVAL_SECONDS = 300.0


class TrainingLeaseHeartbeat:
    """在训练执行期间周期刷新队列 lease。

    该 helper 只维护训练 worker 已领取的 ``QueueMessage``。它不负责
    任务恢复、业务状态变更或训练进程控制。
    """

    def __init__(
        self,
        *,
        queue_backend: QueueBackend,
        queue_message: QueueMessage,
        interval_seconds: float | None = None,
    ) -> None:
        """初始化训练 lease 心跳。

        参数：
        - queue_backend：持有训练任务的队列后端。
        - queue_message：worker 刚领取的训练队列消息。
        - interval_seconds：测试或特殊场景使用的显式刷新间隔。
        """

        self._queue_backend = queue_backend
        self._current_message = queue_message
        self._interval_seconds = self._resolve_interval_seconds(interval_seconds)
        self._stop_event = Event()
        self._state_lock = Lock()
        self._thread: Thread | None = None
        self._lease_lost = False

    @property
    def current_message(self) -> QueueMessage:
        """返回最近一次成功刷新后的队列消息。"""

        with self._state_lock:
            return self._current_message

    @property
    def lease_lost(self) -> bool:
        """返回当前任务 lease 是否已明确被回收或接管。"""

        with self._state_lock:
            return self._lease_lost

    @property
    def is_running(self) -> bool:
        """返回 heartbeat 线程是否仍在运行。"""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """启动后台 heartbeat；重复调用不会创建第二个线程。"""

        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name=f"training-lease-heartbeat-{self._current_message.task_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> QueueMessage:
        """停止并等待 heartbeat 退出，然后返回最新队列消息。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join()
        self._thread = None
        return self.current_message

    def _run(self) -> None:
        """按固定间隔刷新当前训练任务 lease。"""

        while not self._stop_event.wait(self._interval_seconds):
            if self.lease_lost:
                return
            self._refresh_once()

    def _refresh_once(self) -> None:
        """执行一次 lease 刷新并保存最新消息。"""

        queue_message = self.current_message
        try:
            refreshed_message = self._queue_backend.refresh_lease(queue_message)
        except Exception as error:
            self._handle_refresh_error(queue_message=queue_message, error=error)
            return

        with self._state_lock:
            self._current_message = refreshed_message

    def _handle_refresh_error(
        self,
        *,
        queue_message: QueueMessage,
        error: BaseException,
    ) -> None:
        """记录刷新异常，并在可确认时标记 lease 已丢失。"""

        current_task: QueueMessage | None = None
        try:
            current_task = self._queue_backend.get_task(
                queue_name=queue_message.queue_name,
                task_id=queue_message.task_id,
            )
        except Exception:
            current_task = None

        if current_task is not None and self._belongs_to_same_attempt(
            queue_message,
            current_task,
        ):
            with self._state_lock:
                self._current_message = current_task
        elif current_task is not None:
            with self._state_lock:
                self._lease_lost = True

        LOGGER.warning(
            "刷新训练任务 queue lease 失败",
            extra={
                "queue_name": queue_message.queue_name,
                "queue_task_id": queue_message.task_id,
                "worker_id": queue_message.worker_id,
                "attempt_count": queue_message.attempt_count,
                "lease_lost": self.lease_lost,
                "error_type": error.__class__.__name__,
            },
            exc_info=error,
        )

    @staticmethod
    def _belongs_to_same_attempt(
        expected: QueueMessage,
        current: QueueMessage,
    ) -> bool:
        """判断当前队列消息是否仍属于同一次 worker 领取。"""

        return (
            current.status == "leased"
            and current.worker_id == expected.worker_id
            and current.attempt_count == expected.attempt_count
        )

    def _resolve_interval_seconds(self, interval_seconds: float | None) -> float:
        """解析 heartbeat 间隔，默认最多五分钟刷新一次。"""

        if interval_seconds is not None:
            return max(0.01, float(interval_seconds))
        settings = getattr(self._queue_backend, "settings", None)
        queue_lease_timeout_seconds = float(
            getattr(settings, "lease_timeout_seconds", DEFAULT_LEASE_TIMEOUT_SECONDS)
        )
        lease_timeout_seconds = min(
            queue_lease_timeout_seconds,
            TRAINING_LEASE_TIMEOUT_SECONDS,
        )
        return max(
            0.01,
            min(MAX_HEARTBEAT_INTERVAL_SECONDS, lease_timeout_seconds / 3.0),
        )
