"""YOLO26 detection inference 输出适配。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError


def normalize_yolo26_detection_inference_outputs(*, outputs: object, np_module: Any) -> Any:
    """把 YOLO26 detection runtime 输出归一成 NumPy prediction。"""

    normalized = outputs
    if isinstance(normalized, list | tuple):
        if not normalized:
            raise InvalidRequestError("YOLO26 detection inference 输出为空")
        normalized = normalized[0]
    if hasattr(normalized, "detach"):
        normalized = normalized.detach()
    if hasattr(normalized, "cpu"):
        normalized = normalized.cpu()
    if hasattr(normalized, "numpy"):
        normalized = normalized.numpy()
    prediction = np_module.asarray(normalized, dtype=np_module.float32)
    if prediction.ndim == 2:
        prediction = np_module.expand_dims(prediction, axis=0)
    if prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO26 detection inference 输出维度不合法",
            details={"shape": list(prediction.shape)},
        )
    return prediction


__all__ = ["normalize_yolo26_detection_inference_outputs"]
