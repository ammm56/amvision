"""rank0 事件上报工具。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .context import DdpTrainingContext


@dataclass(frozen=True)
class RankZeroReportRecord:
    """rank0 训练事件记录。"""

    kind: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class RankZeroReporter:
    """只允许 rank0 写平台事件、指标和产物。

    rank>0 仍可调用这些方法，但不会触发 sink，避免多进程重复写数据库、
    对象存储或任务事件。
    """

    def __init__(
        self,
        context: DdpTrainingContext,
        sink: Callable[[RankZeroReportRecord], None],
    ) -> None:
        self._context = context
        self._sink = sink

    @property
    def context(self) -> DdpTrainingContext:
        """当前 DDP 上下文。"""

        return self._context

    def emit(
        self,
        kind: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """发送一条 rank0 事件。"""

        if not self._context.is_rank_zero:
            return
        self._sink(
            RankZeroReportRecord(
                kind=kind,
                message=message,
                payload=payload or {},
            )
        )

    def metric(self, message: str, payload: dict[str, Any]) -> None:
        """发送训练或验证指标。"""

        self.emit("metric", message, payload)

    def artifact(self, message: str, payload: dict[str, Any]) -> None:
        """发送训练产物登记事件。"""

        self.emit("artifact", message, payload)

    def control(self, message: str, payload: dict[str, Any] | None = None) -> None:
        """发送控制状态事件。"""

        self.emit("control", message, payload)
