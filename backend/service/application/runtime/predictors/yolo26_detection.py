"""YOLO26 detection 运行时会话入口。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_predictor import (
    OnnxRuntimeYoloPrimaryRuntimeSession,
    OpenVINOYoloPrimaryRuntimeSession,
    PyTorchYoloPrimaryRuntimeSession,
    TensorRTYoloPrimaryRuntimeSession,
)


class PyTorchYolo26RuntimeSession(PyTorchYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLO26 detection 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


class OnnxRuntimeYolo26RuntimeSession(OnnxRuntimeYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLO26 detection 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


class OpenVINOYolo26RuntimeSession(OpenVINOYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 OpenVINO YOLO26 detection 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


class TensorRTYolo26RuntimeSession(TensorRTYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 TensorRT YOLO26 detection 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


__all__ = [
    "OnnxRuntimeYolo26RuntimeSession",
    "OpenVINOYolo26RuntimeSession",
    "PyTorchYolo26RuntimeSession",
    "TensorRTYolo26RuntimeSession",
]
