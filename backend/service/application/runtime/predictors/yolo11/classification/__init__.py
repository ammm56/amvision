"""YOLO11 classification deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11.classification.onnxruntime import (
    OnnxRuntimeYolo11ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.classification.openvino import (
    OpenVINOYolo11ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.classification.pytorch import (
    PyTorchYolo11ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11.classification.tensorrt import (
    TensorRTYolo11ClassificationRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo11ClassificationRuntimeSession",
    "OpenVINOYolo11ClassificationRuntimeSession",
    "PyTorchYolo11ClassificationRuntimeSession",
    "TensorRTYolo11ClassificationRuntimeSession",
]
