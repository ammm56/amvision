"""YOLO11 classification 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_classification_predictor import (
    OnnxRuntimeYoloPrimaryClassificationRuntimeSession,
    OpenVINOYoloPrimaryClassificationRuntimeSession,
    PyTorchYoloPrimaryClassificationRuntimeSession,
    TensorRTYoloPrimaryClassificationRuntimeSession,
)


class PyTorchYolo11ClassificationRuntimeSession(PyTorchYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLO11 classification 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"


class OnnxRuntimeYolo11ClassificationRuntimeSession(OnnxRuntimeYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLO11 classification 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"


class OpenVINOYolo11ClassificationRuntimeSession(OpenVINOYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 OpenVINO YOLO11 classification 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"


class TensorRTYolo11ClassificationRuntimeSession(TensorRTYoloPrimaryClassificationRuntimeSession):
    """已经加载完成并可重复推理的 TensorRT YOLO11 classification 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"


__all__ = [
    "PyTorchYolo11ClassificationRuntimeSession",
    "OnnxRuntimeYolo11ClassificationRuntimeSession",
    "OpenVINOYolo11ClassificationRuntimeSession",
    "TensorRTYolo11ClassificationRuntimeSession",
]
