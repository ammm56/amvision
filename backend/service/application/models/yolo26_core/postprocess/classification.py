"""YOLO26 classification 后处理入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.classification import (
    ClassificationPredictionCategory,
)


def ensure_yolo26_probability_array(
    *,
    prediction_array: object,
    np_module: Any,
) -> Any:
    """把 YOLO26 classification 输出规整为概率数组。"""

    probabilities = _to_numpy_2d_array(prediction_array, np_module=np_module)
    row_sums = probabilities.sum(axis=1, keepdims=True)
    if (
        float(np_module.min(probabilities)) < 0.0
        or float(np_module.max(probabilities)) > 1.0
        or not bool(np_module.allclose(row_sums, 1.0, rtol=1e-3, atol=1e-3))
    ):
        shifted = probabilities - probabilities.max(axis=1, keepdims=True)
        exp_values = np_module.exp(shifted)
        probabilities = exp_values / np_module.maximum(
            exp_values.sum(axis=1, keepdims=True),
            1e-12,
        )
    return probabilities


def build_yolo26_classification_categories(
    *,
    np_module: Any,
    probabilities: Any,
    logits: Any | None,
    labels: tuple[str, ...],
    top_k: int,
) -> tuple[ClassificationPredictionCategory, ...]:
    """把 YOLO26 classification 概率转换为平台 top-k 结果。"""

    if int(probabilities.shape[0]) <= 0:
        return ()
    probability_row = probabilities[0]
    logit_row = logits[0] if logits is not None and int(logits.shape[0]) > 0 else None
    sorted_indices = np_module.argsort(probability_row)[::-1]
    categories: list[ClassificationPredictionCategory] = []
    for class_id in sorted_indices[:top_k].tolist():
        resolved_class_id = int(class_id)
        class_name = (
            labels[resolved_class_id] if 0 <= resolved_class_id < len(labels) else None
        )
        logit_value = None if logit_row is None else float(logit_row[resolved_class_id])
        categories.append(
            ClassificationPredictionCategory(
                class_id=resolved_class_id,
                class_name=class_name,
                probability=round(float(probability_row[resolved_class_id]), 6),
                logit=round(logit_value, 6) if logit_value is not None else None,
            )
        )
    return tuple(categories)


def _to_numpy_2d_array(value: object, *, np_module: Any) -> Any:
    """把 tensor 或数组统一转换为二维 NumPy 数组。"""

    normalized = value
    if hasattr(normalized, "detach"):
        normalized = normalized.detach()
    if hasattr(normalized, "cpu"):
        normalized = normalized.cpu()
    if hasattr(normalized, "numpy"):
        normalized = normalized.numpy()
    array = np_module.asarray(normalized, dtype=np_module.float32)
    if array.ndim == 1:
        array = np_module.expand_dims(array, axis=0)
    if array.ndim != 2:
        raise InvalidRequestError(
            "YOLO26 classification 推理输出维度不合法",
            details={"shape": list(array.shape)},
        )
    return array


__all__ = [
    "build_yolo26_classification_categories",
    "ensure_yolo26_probability_array",
]

