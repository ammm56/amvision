"""YOLO26 pose 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_pose_predictor import (
    OnnxRuntimeYoloPrimaryPoseRuntimeSession,
    OpenVINOYoloPrimaryPoseRuntimeSession,
    PyTorchYoloPrimaryPoseRuntimeSession,
    TensorRTYoloPrimaryPoseRuntimeSession,
)


class PyTorchYolo26PoseRuntimeSession(PyTorchYoloPrimaryPoseRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"


class OnnxRuntimeYolo26PoseRuntimeSession(OnnxRuntimeYoloPrimaryPoseRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"


class OpenVINOYolo26PoseRuntimeSession(OpenVINOYoloPrimaryPoseRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"


class TensorRTYolo26PoseRuntimeSession(TensorRTYoloPrimaryPoseRuntimeSession):
    model_type = "yolo26"
    model_label = "YOLO26"


__all__ = [
    "PyTorchYolo26PoseRuntimeSession",
    "OnnxRuntimeYolo26PoseRuntimeSession",
    "OpenVINOYolo26PoseRuntimeSession",
    "TensorRTYolo26PoseRuntimeSession",
]
