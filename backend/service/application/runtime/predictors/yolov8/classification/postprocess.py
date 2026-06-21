"""YOLOv8 classification runtime 结果组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolov8_core.inference import (
    build_yolov8_classification_inference_categories,
)
from backend.service.application.runtime.predictors.yolov8.classification.contracts import (
    YoloV8ClassificationPredictionCategory,
)


def build_yolov8_classification_runtime_categories(
    *,
    np_module: Any,
    probabilities: Any,
    logits: Any | None,
    labels: tuple[str, ...],
    top_k: int,
) -> tuple[YoloV8ClassificationPredictionCategory, ...]:
    """把 YOLOv8 classification 输出转换为平台 category 结果。"""

    return build_yolov8_classification_inference_categories(
        np_module=np_module,
        probabilities=probabilities,
        logits=logits,
        labels=labels,
        top_k=top_k,
    )


__all__ = ["build_yolov8_classification_runtime_categories"]
