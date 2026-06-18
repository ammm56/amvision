"""YOLOv8 pose TensorRT runtime buffer 工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8_detection_buffer import (
    build_yolov8_detection_numpy_array_from_host_pointer,
    resolve_yolov8_detection_numpy_dtype,
    resolve_yolov8_detection_tensor_byte_size,
)


resolve_yolov8_pose_numpy_dtype = resolve_yolov8_detection_numpy_dtype
resolve_yolov8_pose_tensor_byte_size = resolve_yolov8_detection_tensor_byte_size
build_yolov8_pose_numpy_array_from_host_pointer = (
    build_yolov8_detection_numpy_array_from_host_pointer
)


__all__ = [
    "build_yolov8_pose_numpy_array_from_host_pointer",
    "resolve_yolov8_pose_numpy_dtype",
    "resolve_yolov8_pose_tensor_byte_size",
]
