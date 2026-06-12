"""YOLOv8 obb 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_obb_predictor import (
    OnnxRuntimeYoloPrimaryObbRuntimeSession,
    OpenVINOYoloPrimaryObbRuntimeSession,
    PyTorchYoloPrimaryObbRuntimeSession,
    TensorRTYoloPrimaryObbRuntimeSession,
)


class PyTorchYoloV8ObbRuntimeSession(PyTorchYoloPrimaryObbRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


class OnnxRuntimeYoloV8ObbRuntimeSession(OnnxRuntimeYoloPrimaryObbRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


class OpenVINOYoloV8ObbRuntimeSession(OpenVINOYoloPrimaryObbRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


class TensorRTYoloV8ObbRuntimeSession(TensorRTYoloPrimaryObbRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


__all__ = ["PyTorchYoloV8ObbRuntimeSession", "OnnxRuntimeYoloV8ObbRuntimeSession", "OpenVINOYoloV8ObbRuntimeSession", "TensorRTYoloV8ObbRuntimeSession"]
