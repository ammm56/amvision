"""YOLOv8 obb deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8_obb_onnxruntime import (
    OnnxRuntimeYoloV8ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_obb_openvino import (
    OpenVINOYoloV8ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_obb_pytorch import (
    PyTorchYoloV8ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_obb_tensorrt import (
    TensorRTYoloV8ObbRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYoloV8ObbRuntimeSession",
    "OpenVINOYoloV8ObbRuntimeSession",
    "PyTorchYoloV8ObbRuntimeSession",
    "TensorRTYoloV8ObbRuntimeSession",
]
