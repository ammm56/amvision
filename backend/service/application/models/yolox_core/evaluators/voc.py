"""YOLOX VOC detection 评估结果类型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VocDetectionMetrics:
    """描述一次 VOC detection 评估结果。"""

    map50_95: float
    map50: float
    per_class_metrics: tuple[dict[str, object], ...]
