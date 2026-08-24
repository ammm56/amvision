"""训练 Attempt 的低开销持久控制探针。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal


TrainingControlAction = Literal["none", "save", "pause", "terminate"]


@dataclass(frozen=True)
class TrainingControlDecision:
    """描述一次 batch 安全点观察到的权威训练控制状态。"""

    action: TrainingControlAction = "none"
    requested_at: str | None = None

    @property
    def save_requested(self) -> bool:
        """返回是否请求立即保存。"""

        return self.action == "save"

    @property
    def pause_requested(self) -> bool:
        """返回是否请求暂停。"""

        return self.action == "pause"

    @property
    def terminate_requested(self) -> bool:
        """返回是否请求终止。"""

        return self.action == "terminate"


class TrainingControlProbe:
    """按 monotonic 时间节流持久控制读取，不创建线程或队列。"""

    def __init__(
        self,
        *,
        read_control: Callable[[], TrainingControlDecision],
        poll_interval_seconds: float = 0.25,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        """初始化 Attempt 级探针；首次安全点会立即读取。"""

        interval = float(poll_interval_seconds)
        if interval <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        self._read_control = read_control
        self._poll_interval_seconds = interval
        self._clock = monotonic_clock
        self._next_poll_monotonic = float("-inf")
        self._snapshot = TrainingControlDecision()

    @property
    def snapshot(self) -> TrainingControlDecision:
        """返回最近一次持久读取的不可变控制快照。"""

        return self._snapshot

    def observe(self, *, force: bool = False) -> TrainingControlDecision:
        """在 batch 安全点读取或复用控制快照。"""

        now = self._clock()
        if force or now >= self._next_poll_monotonic:
            snapshot = self._read_control()
            if not isinstance(snapshot, TrainingControlDecision):
                raise TypeError("read_control 必须返回 TrainingControlDecision")
            self._snapshot = snapshot
            self._next_poll_monotonic = now + self._poll_interval_seconds
        return self._snapshot

    def invalidate(self) -> None:
        """清空一次性命令快照，使下一安全点立即读取权威状态。"""

        self._snapshot = TrainingControlDecision()
        self._next_poll_monotonic = float("-inf")


__all__ = [
    "TrainingControlAction",
    "TrainingControlDecision",
    "TrainingControlProbe",
]
