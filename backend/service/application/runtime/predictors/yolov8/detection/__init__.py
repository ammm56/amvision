"""YOLOv8 detection deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.detection.onnxruntime import (
    OnnxRuntimeYoloV8RuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.detection.openvino import (
    OpenVINOYoloV8RuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.detection.pytorch import (
    PyTorchYoloV8RuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.detection.tensorrt import (
    TensorRTYoloV8RuntimeSession,
)


__all__ = [
    "OnnxRuntimeYoloV8RuntimeSession",
    "OpenVINOYoloV8RuntimeSession",
    "PyTorchYoloV8RuntimeSession",
    "TensorRTYoloV8RuntimeSession",
]
