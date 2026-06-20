"""YOLO11 pose deployment predictor 公共入口。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11_pose_onnxruntime import (
    OnnxRuntimeYolo11PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_pose_openvino import (
    OpenVINOYolo11PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_pose_pytorch import (
    PyTorchYolo11PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolo11_pose_tensorrt import (
    TensorRTYolo11PoseRuntimeSession,
)


__all__ = [
    "OnnxRuntimeYolo11PoseRuntimeSession",
    "OpenVINOYolo11PoseRuntimeSession",
    "PyTorchYolo11PoseRuntimeSession",
    "TensorRTYolo11PoseRuntimeSession",
]
