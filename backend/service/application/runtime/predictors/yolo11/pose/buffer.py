"""YOLO11 pose TensorRT buffer 工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.segmentation.buffer import (
    build_yolov8_segmentation_numpy_array_from_host_pointer,
    resolve_yolov8_segmentation_numpy_dtype,
    resolve_yolov8_segmentation_tensor_byte_size,
)


build_yolo11_pose_numpy_array_from_host_pointer = (
    build_yolov8_segmentation_numpy_array_from_host_pointer
)
resolve_yolo11_pose_numpy_dtype = resolve_yolov8_segmentation_numpy_dtype
resolve_yolo11_pose_tensor_byte_size = resolve_yolov8_segmentation_tensor_byte_size


__all__ = [
    "build_yolo11_pose_numpy_array_from_host_pointer",
    "resolve_yolo11_pose_numpy_dtype",
    "resolve_yolo11_pose_tensor_byte_size",
]
