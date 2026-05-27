"""YOLO26 detection 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_predictor import (
    OnnxRuntimeYoloPrimaryRuntimeSession,
    OpenVINOYoloPrimaryRuntimeSession,
    PyTorchYoloPrimaryRuntimeSession,
    TensorRTYoloPrimaryRuntimeSession,
)


class PyTorchYolo26RuntimeSession(PyTorchYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLO26 会话。"""

    model_type = "yolo26"
    model_label = "YOLO26"


class OnnxRuntimeYolo26RuntimeSession(OnnxRuntimeYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLO26 会话。"""

    model_label = "YOLO26"


class OpenVINOYolo26RuntimeSession(OpenVINOYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 OpenVINO YOLO26 会话。"""

    model_label = "YOLO26"


class TensorRTYolo26RuntimeSession(TensorRTYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 TensorRT YOLO26 会话。"""

    model_label = "YOLO26"
