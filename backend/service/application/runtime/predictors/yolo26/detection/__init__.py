"""YOLO26 detection 运行时会话入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo26.detection.onnxruntime import (
    OnnxRuntimeYolo26RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26.detection.openvino import (
    OpenVINOYolo26RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26.detection.pytorch import (
    PyTorchYolo26RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26.detection.tensorrt import (
    TensorRTYolo26RuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo26RuntimeSession",
    "OpenVINOYolo26RuntimeSession",
    "PyTorchYolo26RuntimeSession",
    "TensorRTYolo26RuntimeSession",
]
