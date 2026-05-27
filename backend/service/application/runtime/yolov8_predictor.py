"""YOLOv8 detection 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_predictor import (
    OnnxRuntimeYoloPrimaryRuntimeSession as OnnxRuntimeYoloV8RuntimeSession,
    OpenVINOYoloPrimaryRuntimeSession as OpenVINOYoloV8RuntimeSession,
    PyTorchYoloPrimaryRuntimeSession as PyTorchYoloV8RuntimeSession,
    TensorRTYoloPrimaryRuntimeSession as TensorRTYoloV8RuntimeSession,
)


__all__ = [
    "PyTorchYoloV8RuntimeSession",
    "OnnxRuntimeYoloV8RuntimeSession",
    "OpenVINOYoloV8RuntimeSession",
    "TensorRTYoloV8RuntimeSession",
]
