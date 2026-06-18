"""YOLOv8 classification deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8_classification_onnxruntime import (
    OnnxRuntimeYoloV8ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_classification_openvino import (
    OpenVINOYoloV8ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_classification_pytorch import (
    PyTorchYoloV8ClassificationRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_classification_tensorrt import (
    TensorRTYoloV8ClassificationRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYoloV8ClassificationRuntimeSession",
    "OpenVINOYoloV8ClassificationRuntimeSession",
    "PyTorchYoloV8ClassificationRuntimeSession",
    "TensorRTYoloV8ClassificationRuntimeSession",
]
