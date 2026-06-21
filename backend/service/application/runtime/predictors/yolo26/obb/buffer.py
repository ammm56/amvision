"""YOLO26 OBB TensorRT buffer 工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.common.yolo_runtime_buffer import (
    build_yolo_runtime_numpy_array_from_host_pointer,
    resolve_yolo_runtime_numpy_dtype,
    resolve_yolo_runtime_tensor_byte_size,
)


build_yolo26_obb_numpy_array_from_host_pointer = (
    build_yolo_runtime_numpy_array_from_host_pointer
)
resolve_yolo26_obb_numpy_dtype = resolve_yolo_runtime_numpy_dtype
resolve_yolo26_obb_tensor_byte_size = resolve_yolo_runtime_tensor_byte_size


__all__ = [
    "build_yolo26_obb_numpy_array_from_host_pointer",
    "resolve_yolo26_obb_numpy_dtype",
    "resolve_yolo26_obb_tensor_byte_size",
]
