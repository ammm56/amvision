"""YOLO26 obb 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_obb_predictor import (
    OnnxRuntimeYoloPrimaryObbRuntimeSession, OpenVINOYoloPrimaryObbRuntimeSession,
    PyTorchYoloPrimaryObbRuntimeSession, TensorRTYoloPrimaryObbRuntimeSession,
)

class PyTorchYolo26ObbRuntimeSession(PyTorchYoloPrimaryObbRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"
class OnnxRuntimeYolo26ObbRuntimeSession(OnnxRuntimeYoloPrimaryObbRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"
class OpenVINOYolo26ObbRuntimeSession(OpenVINOYoloPrimaryObbRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"
class TensorRTYolo26ObbRuntimeSession(TensorRTYoloPrimaryObbRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"
__all__ = ["PyTorchYolo26ObbRuntimeSession", "OnnxRuntimeYolo26ObbRuntimeSession", "OpenVINOYolo26ObbRuntimeSession", "TensorRTYolo26ObbRuntimeSession"]
