"""ZeroMQ tracked frame 生命周期表测试。"""

from __future__ import annotations

import time

import pytest

from backend.service.application.errors import ZeroMqTransportCapacityError
from backend.service.infrastructure.integrations.zeromq.zeromq_transport_lifetime import (
    ZeroMqTransportLifetimeRegistry,
)


class _Tracker:
    """测试用可控 tracker。"""

    def __init__(self, *, done: bool = False) -> None:
        self.done = done


def _build_registry(
    *, max_entries: int = 2, max_bytes: int = 16
) -> ZeroMqTransportLifetimeRegistry:
    """构造快速轮询的测试 registry。"""

    return ZeroMqTransportLifetimeRegistry(
        max_entries=max_entries,
        max_bytes=max_bytes,
        tracker_timeout_seconds=0.02,
        reaper_poll_interval_seconds=0.001,
    )


def test_registry_reserves_capacity_before_send_and_releases_after_tracker() -> None:
    """验证容量先预留，且 tracker 完成后才执行一次清理。"""

    registry = _build_registry()
    first = registry.reserve(
        payload_bytes=8, frame_count=2, socket_generation="socket-1"
    )
    second = registry.reserve(
        payload_bytes=8, frame_count=2, socket_generation="socket-1"
    )
    with pytest.raises(ZeroMqTransportCapacityError):
        registry.reserve(
            payload_bytes=1, frame_count=2, socket_generation="socket-1"
        )
    tracker = _Tracker()
    cleanups: list[str] = []
    registry.activate(
        reservation=first,
        tracker=tracker,
        cleanup=lambda: cleanups.append("first"),
    )
    registry.cancel(
        reservation=second,
        cleanup=lambda: cleanups.append("second"),
    )

    registry.reap_once()
    assert cleanups == ["second"]
    tracker.done = True
    assert registry.wait_until_idle(timeout_seconds=1.0) is True
    assert cleanups == ["second", "first"]
    snapshot = registry.snapshot()
    assert snapshot["transport_registry_completed_count"] == 1
    assert snapshot["transport_registry_last_tracker_wait_ms"] >= 0
    assert snapshot["transport_registry_last_tracker_cleanup_ms"] >= 0
    assert registry.close(timeout_seconds=1.0) is True


def test_registry_timeout_quarantines_without_releasing_live_tracker() -> None:
    """验证诊断超时只隔离容量，不会提前释放仍被 libzmq 借用的 view。"""

    registry = _build_registry(max_entries=1)
    reservation = registry.reserve(
        payload_bytes=8, frame_count=2, socket_generation="socket-1"
    )
    tracker = _Tracker()
    cleanups: list[str] = []
    registry.activate(
        reservation=reservation,
        tracker=tracker,
        cleanup=lambda: cleanups.append("released"),
    )
    deadline = time.monotonic() + 1.0
    snapshot = registry.snapshot()
    while (
        time.monotonic() < deadline
        and snapshot["transport_registry_quarantined_count"] == 0
    ):
        time.sleep(0.005)
        snapshot = registry.snapshot()

    assert snapshot["transport_registry_quarantined_count"] == 1
    assert snapshot["transport_registry_tracker_timeout_count"] == 1
    assert cleanups == []
    with pytest.raises(ZeroMqTransportCapacityError):
        registry.reserve(
            payload_bytes=1, frame_count=2, socket_generation="socket-2"
        )

    tracker.done = True
    assert registry.wait_until_idle(timeout_seconds=1.0) is True
    assert cleanups == ["released"]
    snapshot = registry.snapshot()
    assert snapshot["transport_registry_last_tracker_wait_ms"] >= 20
    assert snapshot["transport_registry_last_tracker_cleanup_ms"] >= 0
    assert registry.close(timeout_seconds=1.0) is True
