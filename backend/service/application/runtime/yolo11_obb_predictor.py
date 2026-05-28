"""YOLO11 obb 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_obb_predictor import (
    OnnxRuntimeYoloPrimaryObbRuntimeSession, OpenVINOYoloPrimaryObbRuntimeSession,
    PyTorchYoloPrimaryObbRuntimeSession, TensorRTYoloPrimaryObbRuntimeSession,
)

class PyTorchYolo11ObbRuntimeSession(PyTorchYoloPrimaryObbRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"
class OnnxRuntimeYolo11ObbRuntimeSession(OnnxRuntimeYoloPrimaryObbRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"
class OpenVINOYolo11ObbRuntimeSession(OpenVINOYoloPrimaryObbRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"
class TensorRTYolo11ObbRuntimeSession(TensorRTYoloPrimaryObbRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"
__all__ = ["PyTorchYolo11ObbRuntimeSession", "OnnxRuntimeYolo11ObbRuntimeSession", "OpenVINOYolo11ObbRuntimeSession", "TensorRTYolo11ObbRuntimeSession"]
