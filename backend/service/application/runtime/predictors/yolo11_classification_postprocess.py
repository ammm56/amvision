"""YOLO11 classification runtime 结果组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo11_core.inference import (
    build_yolo11_classification_inference_categories,
)
from backend.service.application.runtime.predictors.yolo11_classification_contracts import (
    Yolo11ClassificationPredictionCategory,
)


def build_yolo11_classification_runtime_categories(
    *,
    np_module: Any,
    probabilities: Any,
    logits: Any | None,
    labels: tuple[str, ...],
    top_k: int,
) -> tuple[Yolo11ClassificationPredictionCategory, ...]:
    """把 YOLO11 classification 输出转换为平台 category 结果。"""

    return build_yolo11_classification_inference_categories(
        np_module=np_module,
        probabilities=probabilities,
        logits=logits,
        labels=labels,
        top_k=top_k,
    )


__all__ = ["build_yolo11_classification_runtime_categories"]
