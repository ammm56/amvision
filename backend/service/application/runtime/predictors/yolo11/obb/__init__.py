"""YOLO11 OBB deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11.obb.onnxruntime import (
    OnnxRuntimeYolo11ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.obb.openvino import (
    OpenVINOYolo11ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.obb.pytorch import (
    PyTorchYolo11ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.obb.tensorrt import (
    TensorRTYolo11ObbRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo11ObbRuntimeSession",
    "OpenVINOYolo11ObbRuntimeSession",
    "PyTorchYolo11ObbRuntimeSession",
    "TensorRTYolo11ObbRuntimeSession",
]
