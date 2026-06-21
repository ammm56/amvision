"""YOLO11 detection 运行时会话入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11.detection.onnxruntime import (
    OnnxRuntimeYolo11RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.detection.openvino import (
    OpenVINOYolo11RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.detection.pytorch import (
    PyTorchYolo11RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.detection.tensorrt import (
    TensorRTYolo11RuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo11RuntimeSession",
    "OpenVINOYolo11RuntimeSession",
    "PyTorchYolo11RuntimeSession",
    "TensorRTYolo11RuntimeSession",
]
