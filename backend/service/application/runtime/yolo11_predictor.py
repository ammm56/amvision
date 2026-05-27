"""YOLO11 detection 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_predictor import (
    OnnxRuntimeYoloPrimaryRuntimeSession,
    OpenVINOYoloPrimaryRuntimeSession,
    PyTorchYoloPrimaryRuntimeSession,
    TensorRTYoloPrimaryRuntimeSession,
)


class PyTorchYolo11RuntimeSession(PyTorchYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 PyTorch YOLO11 会话。"""

    model_type = "yolo11"
    model_label = "YOLO11"


class OnnxRuntimeYolo11RuntimeSession(OnnxRuntimeYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 ONNXRuntime YOLO11 会话。"""

    model_label = "YOLO11"


class OpenVINOYolo11RuntimeSession(OpenVINOYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 OpenVINO YOLO11 会话。"""

    model_label = "YOLO11"


class TensorRTYolo11RuntimeSession(TensorRTYoloPrimaryRuntimeSession):
    """已经加载完成并可重复推理的 TensorRT YOLO11 会话。"""

    model_label = "YOLO11"
