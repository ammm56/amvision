"""YOLOv8 pose 单图推理实现。"""

from __future__ import annotations

from backend.service.application.runtime.yolo_primary_pose_predictor import (
    OnnxRuntimeYoloPrimaryPoseRuntimeSession,
    OpenVINOYoloPrimaryPoseRuntimeSession,
    PyTorchYoloPrimaryPoseRuntimeSession,
    TensorRTYoloPrimaryPoseRuntimeSession,
)


class PyTorchYoloV8PoseRuntimeSession(PyTorchYoloPrimaryPoseRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


class OnnxRuntimeYoloV8PoseRuntimeSession(OnnxRuntimeYoloPrimaryPoseRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


class OpenVINOYoloV8PoseRuntimeSession(OpenVINOYoloPrimaryPoseRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


class TensorRTYoloV8PoseRuntimeSession(TensorRTYoloPrimaryPoseRuntimeSession):
    model_type = "yolov8"
    model_label = "YOLOv8"


__all__ = [
    "PyTorchYoloV8PoseRuntimeSession",
    "OnnxRuntimeYoloV8PoseRuntimeSession",
    "OpenVINOYoloV8PoseRuntimeSession",
    "TensorRTYoloV8PoseRuntimeSession",
]
