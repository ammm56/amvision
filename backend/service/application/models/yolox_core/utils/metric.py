"""YOLOX 训练指标缓冲工具。"""

from __future__ import annotations

import functools
from collections import defaultdict, deque
from typing import Any

import numpy as np


class AverageMeter:
    """跟踪单个指标的滑动平均值和全局平均值。"""

    def __init__(self, window_size: int = 50) -> None:
        """初始化指标窗口。"""

        self._deque = deque(maxlen=window_size)
        self._total = 0.0
        self._count = 0

    def update(self, value: Any) -> None:
        """追加一个新指标值。"""

        self._deque.append(value)
        self._count += 1
        self._total += float(value)

    @property
    def median(self) -> float:
        """返回当前窗口中位数。"""

        return float(np.median(np.array(list(self._deque))))

    @property
    def avg(self) -> float:
        """返回当前窗口平均值。"""

        return float(np.array(list(self._deque)).mean())

    @property
    def global_avg(self) -> float:
        """返回全局平均值。"""

        return self._total / max(self._count, 1e-5)

    @property
    def latest(self) -> Any:
        """返回最近一次指标值。"""

        return self._deque[-1] if self._deque else None

    @property
    def total(self) -> float:
        """返回累计值。"""

        return self._total

    def reset(self) -> None:
        """清空窗口和累计值。"""

        self._deque.clear()
        self._total = 0.0
        self._count = 0

    def clear(self) -> None:
        """只清空当前滑动窗口。"""

        self._deque.clear()


class MeterBuffer(defaultdict):
    """维护多个指标的滑动窗口。"""

    def __init__(self, window_size: int = 20) -> None:
        """初始化指标缓冲区。"""

        super().__init__(functools.partial(AverageMeter, window_size=window_size))

    def reset(self) -> None:
        """重置所有指标。"""

        for value in self.values():
            value.reset()

    def get_filtered_meter(self, filter_key: str = "time") -> dict[str, AverageMeter]:
        """按 key 关键字过滤指标。"""

        return {key: value for key, value in self.items() if filter_key in key}

    def update(self, values: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """批量更新指标。"""

        payload = dict(values or {})
        payload.update(kwargs)
        for key, value in payload.items():
            if hasattr(value, "detach"):
                value = value.detach()
            self[key].update(value)

    def clear_meters(self) -> None:
        """清空全部指标的滑动窗口。"""

        for value in self.values():
            value.clear()
