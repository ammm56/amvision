"""YOLO26 classification 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_classification_predictor import (
    OnnxRuntimeYoloPrimaryClassificationRuntimeSession,
    PyTorchYoloPrimaryClassificationRuntimeSession,
)


class PyTorchYolo26ClassificationRuntimeSession(PyTorchYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLO26 classification 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


class OnnxRuntimeYolo26ClassificationRuntimeSession(OnnxRuntimeYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLO26 classification 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


__all__ = [
    "PyTorchYolo26ClassificationRuntimeSession",
    "OnnxRuntimeYolo26ClassificationRuntimeSession",
]
