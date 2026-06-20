"""YOLO11 classification inference 输出适配。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo11_core.postprocess import (
    build_yolo11_classification_categories,
    ensure_yolo11_probability_array,
)
from backend.service.application.runtime.contracts.classification import (
    ClassificationPredictionCategory,
)


def normalize_yolo11_classification_inference_outputs(
    *,
    outputs: object,
    np_module: Any,
) -> tuple[Any, Any | None]:
    """归一化 YOLO11 classification inference 输出。"""

    if isinstance(outputs, list | tuple):
        if len(outputs) >= 2:
            probabilities = ensure_yolo11_probability_array(
                prediction_array=outputs[0],
                np_module=np_module,
            )
            logits = _to_numpy_2d_array(outputs[1], np_module=np_module)
            return probabilities, logits
        if len(outputs) == 1:
            outputs = outputs[0]
        else:
            raise InvalidRequestError("YOLO11 classification inference 输出为空")

    probabilities = ensure_yolo11_probability_array(
        prediction_array=outputs,
        np_module=np_module,
    )
    return probabilities, None


def build_yolo11_classification_inference_categories(
    *,
    np_module: Any,
    probabilities: Any,
    logits: Any | None,
    labels: tuple[str, ...],
    top_k: int,
) -> tuple[ClassificationPredictionCategory, ...]:
    """把 YOLO11 classification inference 输出转换为平台 category 结果。"""

    return build_yolo11_classification_categories(
        np_module=np_module,
        probabilities=probabilities,
        logits=logits,
        labels=labels,
        top_k=top_k,
    )


def _to_numpy_2d_array(value: object, *, np_module: Any) -> Any:
    """把 tensor 或数组转换为二维 NumPy 数组。"""

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
            "YOLO11 classification inference 输出维度不合法",
            details={"shape": list(array.shape)},
        )
    return array


__all__ = [
    "build_yolo11_classification_inference_categories",
    "normalize_yolo11_classification_inference_outputs",
]
