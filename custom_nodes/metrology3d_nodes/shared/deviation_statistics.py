"""完整目标的有界统计；生产计算和详细证据校验共用同一数值规则。"""

from math import fsum, sqrt

import numpy as np

from backend.contracts.workflows.deviation3d import (
    DeviationExtreme,
    DeviationStatistics,
)
from backend.service.application.errors import InvalidRequestError


class DeviationStatisticsAccumulator:
    """只保留极值、计数与来源，不持有已处理点或按块增长的列表。"""

    def __init__(self):
        """常量规模状态；原行号优先于逻辑行号决定极值显示代表。"""
        self.count = 0
        self.minimum, self.maximum = np.inf, -np.inf
        self.low = self.high = None
        self.low_ties = self.high_ties = 0

    def update(self, values, source, *, start):
        """接收一个有界块；全部有限偏差参与，不能按支持成败删点。"""
        finite = np.flatnonzero(np.isfinite(values))
        if not len(finite):
            return
        valid = values[finite]
        self.count += len(valid)
        a, b = float(valid.min()), float(valid.max())
        for smallest, value in ((True, a), (False, b)):
            selected = finite[valid == value]
            chosen = int(selected[np.argmin(source[selected])])
            identity = (int(source[chosen]), start + chosen)
            if smallest:
                if value < self.minimum:
                    self.minimum, self.low, self.low_ties = (
                        value,
                        identity,
                        len(selected),
                    )
                elif value == self.minimum:
                    self.low, self.low_ties = (
                        min(self.low, identity),
                        self.low_ties + len(selected),
                    )
            elif value > self.maximum:
                self.maximum, self.high, self.high_ties = value, identity, len(selected)
            elif value == self.maximum:
                self.high, self.high_ties = (
                    min(self.high, identity),
                    self.high_ties + len(selected),
                )

    def finish(self, value_chunks, *, cancel):
        """以可重读的只读块做原归一化 fsum，不重跑支持搜索或拟合。"""
        if not self.count:
            return None
        scale = max(abs(self.minimum), abs(self.maximum))

        def normalized(squared):
            """两遍稳定求和，不用 tee 缓存完整目标。"""
            for values in value_chunks():
                cancel()
                for value in values:
                    if np.isfinite(value):
                        ratio = float(value) / scale
                        yield ratio * ratio if squared else ratio

        mean = (
            self.minimum
            if self.minimum == self.maximum
            else (fsum(normalized(False)) / self.count) * scale
        )
        rms = sqrt(fsum(normalized(True)) / self.count) * scale if scale else 0.0
        span = self.maximum - self.minimum
        if not all(np.isfinite(v) for v in (mean, rms, span)):
            raise InvalidRequestError("基准偏差统计超出有限数值范围")
        cancel()
        return DeviationStatistics(
            count=self.count,
            minimum=self.minimum,
            maximum=self.maximum,
            peak_to_valley=span,
            mean=mean,
            rms=rms,
            minimum_source=DeviationExtreme(
                source_index=self.low[0],
                logical_index=self.low[1],
                tie_count=self.low_ties,
            ),
            maximum_source=DeviationExtreme(
                source_index=self.high[0],
                logical_index=self.high[1],
                tie_count=self.high_ties,
            ),
        )


def deviation_statistics(arrays, *, chunk_rows, cancel):
    """详细证据表的读回校验，使用与正常测量相同的统计实现。"""
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise InvalidRequestError("偏差统计块大小必须为正整数")
    values, source = arrays["deviation"][:, 0], arrays["source_index"][:, 0]
    accumulator = DeviationStatisticsAccumulator()
    for start in range(0, len(values), chunk_rows):
        cancel()
        accumulator.update(
            values[start : start + chunk_rows],
            source[start : start + chunk_rows],
            start=start,
        )

    def chunks():
        """只产生当前切片，调用方持有读回表的借用和预算。"""
        for start in range(0, len(values), chunk_rows):
            yield values[start : start + chunk_rows]

    return accumulator.finish(chunks, cancel=cancel)
