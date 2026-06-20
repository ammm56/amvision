"""YOLO26 detection 运行时会话入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo26_detection_onnxruntime import (
    OnnxRuntimeYolo26RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26_detection_openvino import (
    OpenVINOYolo26RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26_detection_pytorch import (
    PyTorchYolo26RuntimeSession,
)
from backend.service.application.runtime.predictors.yolo26_detection_tensorrt import (
    TensorRTYolo26RuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo26RuntimeSession",
    "OpenVINOYolo26RuntimeSession",
    "PyTorchYolo26RuntimeSession",
    "TensorRTYolo26RuntimeSession",
]
