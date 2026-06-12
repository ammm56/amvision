"""YOLOv8 detection 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_predictor import (
    OnnxRuntimeYoloPrimaryRuntimeSession,
    OpenVINOYoloPrimaryRuntimeSession,
    PyTorchYoloPrimaryRuntimeSession,
    TensorRTYoloPrimaryRuntimeSession,
)


class PyTorchYoloV8RuntimeSession(PyTorchYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLOv8 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


class OnnxRuntimeYoloV8RuntimeSession(OnnxRuntimeYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLOv8 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


class OpenVINOYoloV8RuntimeSession(OpenVINOYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 OpenVINO YOLOv8 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


class TensorRTYoloV8RuntimeSession(TensorRTYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 TensorRT YOLOv8 会话。"""

    model_type = "yolov8"
    model_label = "YOLOv8"


__all__ = [
    "PyTorchYoloV8RuntimeSession",
    "OnnxRuntimeYoloV8RuntimeSession",
    "OpenVINOYoloV8RuntimeSession",
    "TensorRTYoloV8RuntimeSession",
]
