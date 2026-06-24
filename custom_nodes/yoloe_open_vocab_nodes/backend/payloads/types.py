"""YOLOE payload 与运行时数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class YoloePromptItem:
    """描述一条文本提示。"""

    prompt_id: str
    text: str
    display_name: str
    negative: bool = False
    language: str | None = None


@dataclass(frozen=True)
class YoloePromptGroup:
    """描述一个按 prompt_id 聚合后的文本提示组。"""

    prompt_id: str
    display_name: str
    positive_texts: tuple[str, ...]
    negative_texts: tuple[str, ...]
    languages: tuple[str, ...]


@dataclass(frozen=True)
class YoloeVisualPromptItem:
    """描述一条视觉提示。"""

    prompt_id: str
    prompt_kind: str
    bbox_xyxy: tuple[float, float, float, float] | None
    point_xy: tuple[float, float] | None
    point_label: str | None
    polygon_xy: tuple[tuple[float, float], ...] | None
    prompt_mask: np.ndarray | None
    display_name: str
    prompt_kinds: tuple[str, ...] = ()
    raw_item_count: int = 1


@dataclass(frozen=True)
class YoloePretrainedVariant:
    """描述一个 YOLOE 预训练权重目录。"""

    model_series: str
    model_scale: str
    prompt_free: bool
    variant_name: str
    manifest_path: Path
    checkpoint_path: Path
    model_name: str
    task_type: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class YoloeDetectionPrediction:
    """描述一次 YOLOE 推理结果。"""

    detections: tuple[dict[str, object], ...]
    summary: dict[str, object]
    regions: tuple[dict[str, object], ...] = ()


YoloeTextPromptPrediction = YoloeDetectionPrediction


__all__ = [
    "YoloeDetectionPrediction",
    "YoloePretrainedVariant",
    "YoloePromptGroup",
    "YoloePromptItem",
    "YoloeTextPromptPrediction",
    "YoloeVisualPromptItem",
]
