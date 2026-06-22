"""workflow runtime worker 心跳循环。"""

from __future__ import annotations

from collections.abc import Callable
from multiprocessing.queues import Queue
from threading import Event
from typing import Any


def run_workflow_runtime_heartbeat_loop(
    *,
    stop_event: Event,
    interval_seconds: float,
    response_queue: Queue[Any],
    build_message: Callable[..., dict[str, object]],
) -> None:
    """按固定间隔向父进程主动发送 runtime-heartbeat。"""

    if interval_seconds <= 0:
        return
    while not stop_event.wait(timeout=max(0.1, interval_seconds)):
        try:
            response_queue.put(build_message(message_type="runtime-heartbeat"))
        except Exception:
            return
