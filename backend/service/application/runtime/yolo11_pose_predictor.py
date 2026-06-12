"""YOLO11 pose 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_pose_predictor import (
    OnnxRuntimeYoloPrimaryPoseRuntimeSession,
    OpenVINOYoloPrimaryPoseRuntimeSession,
    PyTorchYoloPrimaryPoseRuntimeSession,
    TensorRTYoloPrimaryPoseRuntimeSession,
)


class PyTorchYolo11PoseRuntimeSession(PyTorchYoloPrimaryPoseRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"


class OnnxRuntimeYolo11PoseRuntimeSession(OnnxRuntimeYoloPrimaryPoseRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"


class OpenVINOYolo11PoseRuntimeSession(OpenVINOYoloPrimaryPoseRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"


class TensorRTYolo11PoseRuntimeSession(TensorRTYoloPrimaryPoseRuntimeSession):
    model_type = "yolo11"
    model_label = "YOLO11"


__all__ = [
    "PyTorchYolo11PoseRuntimeSession",
    "OnnxRuntimeYolo11PoseRuntimeSession",
    "OpenVINOYolo11PoseRuntimeSession",
    "TensorRTYolo11PoseRuntimeSession",
]
