"""YOLO26 classification runtime 结果组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo26_core.inference import (
    build_yolo26_classification_inference_categories,
)
from backend.service.application.runtime.predictors.yolo26.classification.contracts import (
    Yolo26ClassificationPredictionCategory,
)


def build_yolo26_classification_runtime_categories(
    *,
    np_module: Any,
    probabilities: Any,
    logits: Any | None,
    labels: tuple[str, ...],
    top_k: int,
) -> tuple[Yolo26ClassificationPredictionCategory, ...]:
    """把 YOLO26 classification 输出转换为平台 category 结果。"""

    return build_yolo26_classification_inference_categories(
        np_module=np_module,
        probabilities=probabilities,
        logits=logits,
        labels=labels,
        top_k=top_k,
    )


__all__ = ["build_yolo26_classification_runtime_categories"]

