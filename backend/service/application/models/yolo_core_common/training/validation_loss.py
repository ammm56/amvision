"""训练期验证损失的样本加权统计。"""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import SupportsFloat

from backend.service.application.models.yolo_core_common.training.optimizer_step import (
    YoloTrainingNumericalError,
)


class YoloValidationLossAccumulator:
    """按有效样本数汇总批次损失，沿用训练的总损失与分项口径。"""

    def __init__(self, *, all_components_are_sums: bool = False) -> None:
        """初始化统计，允许所有损失分项直接使用批次总和。"""

        self._totals: dict[str, float] = {}
        self._sample_count = 0
        self._all_components_are_sums = all_components_are_sums

    def add_batch(
        self, *, payload: Mapping[str, SupportsFloat], sample_count: int
    ) -> None:
        """累计批次总损失，以及乘以样本数的损失分项平均值。"""

        for name, batch_value in payload.items():
            value = float(batch_value)
            if not math.isfinite(value):
                raise YoloTrainingNumericalError(f"验证产生非有限损失 {name}={value}")
            self._totals[name] = self._totals.get(name, 0.0) + (
                value
                if self._all_components_are_sums or name == "loss"
                else value * sample_count
            )
        self._sample_count += sample_count

    def metrics(self) -> dict[str, float]:
        """返回每个有效样本的平均损失。"""

        divisor = max(1, self._sample_count)
        return {name: round(total / divisor, 6) for name, total in self._totals.items()}
