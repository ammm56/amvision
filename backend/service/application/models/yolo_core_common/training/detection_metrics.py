"""YOLO detection 训练与验证指标归一化。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


YOLO_DETECTION_LOSS_METRIC_NAMES = (
    "loss",
    "class_loss",
    "box_loss",
    "dfl_loss",
)


@dataclass
class YoloDetectionLossAccumulator:
    """按样本数汇总不同大小 batch 的 YOLO detection loss。"""

    weighted_totals: dict[str, float] = field(
        default_factory=lambda: {
            name: 0.0 for name in YOLO_DETECTION_LOSS_METRIC_NAMES
        }
    )
    sample_count: int = 0

    def add(
        self,
        *,
        metrics: dict[str, float],
        batch_sample_count: int,
    ) -> None:
        """加入一个已归一化 batch，避免最后一个小 batch 获得相同权重。"""

        resolved_batch_sample_count = int(batch_sample_count)
        if resolved_batch_sample_count <= 0:
            raise ValueError("YOLO detection loss 汇总要求 batch_sample_count 大于 0")
        missing_names = [
            name for name in YOLO_DETECTION_LOSS_METRIC_NAMES if name not in metrics
        ]
        if missing_names:
            raise ValueError(
                "YOLO detection loss 缺少指标: " + ", ".join(missing_names)
            )
        for name in YOLO_DETECTION_LOSS_METRIC_NAMES:
            value = float(metrics[name])
            if not math.isfinite(value):
                raise ValueError(f"YOLO detection loss 指标不是有限数值: {name}={value}")
            self.weighted_totals[name] += value * resolved_batch_sample_count
        self.sample_count += resolved_batch_sample_count

    def mean(self, *, ndigits: int = 6) -> dict[str, float]:
        """返回全部样本的平均 loss；空集合返回同 schema 的零值。"""

        if self.sample_count <= 0:
            return {name: 0.0 for name in YOLO_DETECTION_LOSS_METRIC_NAMES}
        return {
            name: round(total / self.sample_count, ndigits)
            for name, total in self.weighted_totals.items()
        }


def normalize_yolo_detection_loss_metrics(
    *,
    loss_components: dict[str, Any],
    batch_sample_count: int,
) -> dict[str, float]:
    """把反向传播用 batch-scaled total loss 转成可比较的样本均值。

    Ultralytics detection loss 的 ``loss`` 为各加权分量之和再乘当前 batch
    样本数，而 ``class_loss``、``box_loss``、``dfl_loss`` 已是当前 batch
    的加权均值。训练仍使用原始 ``loss`` 反向传播，只有日志和报告做归一化，
    避免 batch size 或最后一个不完整 batch 改变指标量纲。
    """

    resolved_batch_sample_count = int(batch_sample_count)
    if resolved_batch_sample_count <= 0:
        raise ValueError("YOLO detection loss 指标归一化要求 batch_sample_count 大于 0")
    missing_names = [
        name for name in YOLO_DETECTION_LOSS_METRIC_NAMES
        if name not in loss_components
    ]
    if missing_names:
        raise ValueError(
            "YOLO detection loss 缺少指标: " + ", ".join(missing_names)
        )

    normalized = {
        name: _read_scalar(loss_components[name])
        for name in YOLO_DETECTION_LOSS_METRIC_NAMES
    }
    normalized["loss"] /= float(resolved_batch_sample_count)
    for name, value in normalized.items():
        if not math.isfinite(value):
            raise ValueError(f"YOLO detection loss 指标不是有限数值: {name}={value}")
    return normalized


def _read_scalar(value: Any) -> float:
    """读取 tensor 或普通数值中的标量。"""

    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    item = getattr(value, "item", None)
    if callable(item):
        value = item()
    return float(value)


__all__ = [
    "YOLO_DETECTION_LOSS_METRIC_NAMES",
    "YoloDetectionLossAccumulator",
    "normalize_yolo_detection_loss_metrics",
]
