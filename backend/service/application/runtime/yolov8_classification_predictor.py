"""YOLOv8 classification 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_classification_predictor import (
    OnnxRuntimeYoloPrimaryClassificationRuntimeSession,
    PyTorchYoloPrimaryClassificationRuntimeSession,
)


class PyTorchYoloV8ClassificationRuntimeSession(PyTorchYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLOv8 classification 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


class OnnxRuntimeYoloV8ClassificationRuntimeSession(OnnxRuntimeYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLOv8 classification 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


__all__ = [
    "PyTorchYoloV8ClassificationRuntimeSession",
    "OnnxRuntimeYoloV8ClassificationRuntimeSession",
]
