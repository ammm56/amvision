"""YOLOv8 pose deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.pose.onnxruntime import (
    OnnxRuntimeYoloV8PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.pose.openvino import (
    OpenVINOYoloV8PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.pose.pytorch import (
    PyTorchYoloV8PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8.pose.tensorrt import (
    TensorRTYoloV8PoseRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYoloV8PoseRuntimeSession",
    "OpenVINOYoloV8PoseRuntimeSession",
    "PyTorchYoloV8PoseRuntimeSession",
    "TensorRTYoloV8PoseRuntimeSession",
]
