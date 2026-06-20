"""YOLO11 detection 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11_detection_onnxruntime import (
    OnnxRuntimeYolo11RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_detection_openvino import (
    OpenVINOYolo11RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_detection_pytorch import (
    PyTorchYolo11RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_detection_tensorrt import (
    TensorRTYolo11RuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo11RuntimeSession",
    "OpenVINOYolo11RuntimeSession",
    "PyTorchYolo11RuntimeSession",
    "TensorRTYolo11RuntimeSession",
]
