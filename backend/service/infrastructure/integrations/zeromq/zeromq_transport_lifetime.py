"""ZeroMQ 图片结果发送期间的进程内生命周期表。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, RLock, Thread
from time import monotonic, sleep
from typing import Protocol
from uuid import uuid4

from backend.service.application.errors import ZeroMqTransportCapacityError


class ZeroMqMessageTracker(Protocol):
    """定义 pyzmq MessageTracker 所需的最小只读接口。"""

    @property
    def done(self) -> bool:
        """返回 libzmq 是否已经不再借用发送 frame。"""

        ...


@dataclass(frozen=True)
class ZeroMqTransportReservation:
    """描述在发送第一帧前预留的一次生命周期容量。"""

    reservation_id: str
    payload_bytes: int
    frame_count: int
    socket_generation: str


@dataclass
class _ActiveTransport:
    """保存一次正在由 libzmq 借用的发送及其清理责任。"""

    reservation: ZeroMqTransportReservation
    tracker: ZeroMqMessageTracker
    cleanup: Callable[[], None]
    activated_at: float
    timeout_reported: bool = False


class ZeroMqTransportLifetimeRegistry:
    """有界保存 tracker、reader guard 和 output lease 的清理责任。

    该对象只运行在持有 ``zmq.Frame`` 的 backend adapter 进程内。Broker 不读取
    tracker，也不会在 tracker 完成前复用对应 LocalBuffer slot。
    """

    def __init__(
        self,
        *,
        max_entries: int,
        max_bytes: int,
        tracker_timeout_seconds: float,
        reaper_poll_interval_seconds: float,
    ) -> None:
        """初始化固定容量和后台回收器。"""

        if max_entries <= 0 or max_bytes <= 0:
            raise ValueError("ZeroMQ transport registry 容量必须大于 0")
        if tracker_timeout_seconds <= 0 or reaper_poll_interval_seconds <= 0:
            raise ValueError("ZeroMQ transport registry 时间参数必须大于 0")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._tracker_timeout_seconds = tracker_timeout_seconds
        self._reaper_poll_interval_seconds = reaper_poll_interval_seconds
        self._reservations: dict[str, ZeroMqTransportReservation] = {}
        self._active: dict[str, _ActiveTransport] = {}
        self._lock = RLock()
        self._stop_event = Event()
        self._cleanup_failure_count = 0
        self._tracker_timeout_count = 0
        self._completed_count = 0
        self._last_tracker_wait_ms = 0.0
        self._last_tracker_cleanup_ms = 0.0
        self._thread: Thread | None = None

    def reserve(
        self,
        *,
        payload_bytes: int,
        frame_count: int,
        socket_generation: str,
    ) -> ZeroMqTransportReservation:
        """在任何 multipart frame 发出前原子预留 entry 与字节容量。"""

        if payload_bytes < 0 or frame_count <= 0 or not socket_generation.strip():
            raise ValueError("ZeroMQ transport reservation 参数不合法")
        with self._lock:
            current_entries = len(self._reservations) + len(self._active)
            current_bytes = sum(
                item.payload_bytes for item in self._reservations.values()
            ) + sum(
                item.reservation.payload_bytes for item in self._active.values()
            )
            if (
                current_entries >= self._max_entries
                or current_bytes + payload_bytes > self._max_bytes
            ):
                raise ZeroMqTransportCapacityError(
                    details={
                        "max_entries": self._max_entries,
                        "max_bytes": self._max_bytes,
                        "active_entries": current_entries,
                        "active_bytes": current_bytes,
                        "requested_bytes": payload_bytes,
                        "requested_frame_count": frame_count,
                        "socket_generation": socket_generation,
                    }
                )
            reservation = ZeroMqTransportReservation(
                reservation_id=f"zeromq-transport-{uuid4().hex}",
                payload_bytes=payload_bytes,
                frame_count=frame_count,
                socket_generation=socket_generation,
            )
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    def activate(
        self,
        *,
        reservation: ZeroMqTransportReservation,
        tracker: ZeroMqMessageTracker,
        cleanup: Callable[[], None],
    ) -> None:
        """发送已开始后把预留转换为不可丢失的 tracker 清理责任。"""

        with self._lock:
            current = self._reservations.pop(reservation.reservation_id, None)
            if current != reservation:
                raise RuntimeError("ZeroMQ transport reservation 已失效")
            self._active[reservation.reservation_id] = _ActiveTransport(
                reservation=reservation,
                tracker=tracker,
                cleanup=cleanup,
                activated_at=monotonic(),
            )
        self._ensure_reaper_started()

    def cancel(
        self,
        *,
        reservation: ZeroMqTransportReservation,
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        """在发送尚未开始时撤销预留并安全执行本地清理。"""

        with self._lock:
            current = self._reservations.pop(reservation.reservation_id, None)
        if current is None:
            return
        if cleanup is not None:
            self._run_cleanup(cleanup)

    def reap_once(self) -> int:
        """回收所有 tracker 已完成的 entry；超时 entry 只诊断、不提前释放。"""

        ready: list[_ActiveTransport] = []
        now = monotonic()
        with self._lock:
            for reservation_id, item in tuple(self._active.items()):
                try:
                    tracker_done = item.tracker.done
                except Exception:
                    tracker_done = False
                if tracker_done:
                    ready.append(self._active.pop(reservation_id))
                    continue
                if (
                    not item.timeout_reported
                    and now - item.activated_at >= self._tracker_timeout_seconds
                ):
                    item.timeout_reported = True
                    self._tracker_timeout_count += 1
        for item in ready:
            cleanup_started_at = monotonic()
            self._run_cleanup(item.cleanup)
            cleanup_ms = max(0.0, monotonic() - cleanup_started_at) * 1_000
            tracker_wait_ms = max(0.0, now - item.activated_at) * 1_000
            with self._lock:
                self._last_tracker_wait_ms = round(tracker_wait_ms, 3)
                self._last_tracker_cleanup_ms = round(cleanup_ms, 3)
        with self._lock:
            self._completed_count += len(ready)
        return len(ready)

    def snapshot(self) -> dict[str, int | float]:
        """返回 health 页面可使用的固定容量与回收指标。"""

        with self._lock:
            reserved_bytes = sum(
                item.payload_bytes for item in self._reservations.values()
            )
            active_bytes = sum(
                item.reservation.payload_bytes for item in self._active.values()
            )
            quarantined_count = sum(
                1 for item in self._active.values() if item.timeout_reported
            )
            return {
                "transport_registry_max_entries": self._max_entries,
                "transport_registry_max_bytes": self._max_bytes,
                "transport_registry_reserved_count": len(self._reservations),
                "transport_registry_active_count": len(self._active),
                "transport_registry_active_bytes": reserved_bytes + active_bytes,
                "transport_registry_quarantined_count": quarantined_count,
                "transport_registry_tracker_timeout_count": self._tracker_timeout_count,
                "transport_registry_cleanup_failure_count": self._cleanup_failure_count,
                "transport_registry_completed_count": self._completed_count,
                "transport_registry_last_tracker_wait_ms": (
                    self._last_tracker_wait_ms
                ),
                "transport_registry_last_tracker_cleanup_ms": (
                    self._last_tracker_cleanup_ms
                ),
            }

    def wait_until_idle(self, *, timeout_seconds: float) -> bool:
        """等待已开始发送的 tracker 完成，期间绝不强制释放其资源。"""

        deadline = monotonic() + max(timeout_seconds, 0.0)
        while True:
            self.reap_once()
            with self._lock:
                if not self._reservations and not self._active:
                    return True
            if monotonic() >= deadline:
                return False
            sleep(min(self._reaper_poll_interval_seconds, max(deadline - monotonic(), 0.0)))

    def close(self, *, timeout_seconds: float) -> bool:
        """仅在 registry 已排空时停止 reaper；未完成 tracker 保持责任。"""

        idle = self.wait_until_idle(timeout_seconds=timeout_seconds)
        if not idle:
            return False
        self._stop_event.set()
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=max(timeout_seconds, 0.1))
        return not thread.is_alive()

    def _ensure_reaper_started(self) -> None:
        """第一次 tracked send 激活时才创建后台线程。"""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._stop_event.is_set():
                raise RuntimeError("ZeroMQ transport registry 已关闭")
            self._thread = Thread(
                target=self._reaper_loop,
                name="zeromq-transport-reaper",
                daemon=True,
            )
            self._thread.start()

    def _reaper_loop(self) -> None:
        """持续回收完成的 tracker，保证 TriggerSource 停止后仍可释放。"""

        while not self._stop_event.wait(self._reaper_poll_interval_seconds):
            self.reap_once()

    def _run_cleanup(self, cleanup: Callable[[], None]) -> None:
        """执行一次清理；失败只计数，Broker 仍可按 deadline 恢复。"""

        try:
            cleanup()
        except Exception:
            with self._lock:
                self._cleanup_failure_count += 1
