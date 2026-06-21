"""YOLO26 pose TensorRT buffer 工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo_runtime_buffer import (
    build_yolo_runtime_numpy_array_from_host_pointer,
    resolve_yolo_runtime_numpy_dtype,
    resolve_yolo_runtime_tensor_byte_size,
)


build_yolo26_pose_numpy_array_from_host_pointer = (
    build_yolo_runtime_numpy_array_from_host_pointer
)
resolve_yolo26_pose_numpy_dtype = resolve_yolo_runtime_numpy_dtype
resolve_yolo26_pose_tensor_byte_size = resolve_yolo_runtime_tensor_byte_size


__all__ = [
    "build_yolo26_pose_numpy_array_from_host_pointer",
    "resolve_yolo26_pose_numpy_dtype",
    "resolve_yolo26_pose_tensor_byte_size",
]
