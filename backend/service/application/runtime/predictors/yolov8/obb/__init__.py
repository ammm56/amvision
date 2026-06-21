"""YOLOv8 obb deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.obb.onnxruntime import (
    OnnxRuntimeYoloV8ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.obb.openvino import (
    OpenVINOYoloV8ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.obb.pytorch import (
    PyTorchYoloV8ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.obb.tensorrt import (
    TensorRTYoloV8ObbRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYoloV8ObbRuntimeSession",
    "OpenVINOYoloV8ObbRuntimeSession",
    "PyTorchYoloV8ObbRuntimeSession",
    "TensorRTYoloV8ObbRuntimeSession",
]
