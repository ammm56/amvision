"""YOLO11 classification TensorRT runtime buffer 工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11_segmentation_buffer import (
    build_yolo11_segmentation_numpy_array_from_host_pointer,
    resolve_yolo11_segmentation_numpy_dtype,
    resolve_yolo11_segmentation_tensor_byte_size,
)


resolve_yolo11_classification_numpy_dtype = resolve_yolo11_segmentation_numpy_dtype
resolve_yolo11_classification_tensor_byte_size = (
    resolve_yolo11_segmentation_tensor_byte_size
)
build_yolo11_classification_numpy_array_from_host_pointer = (
    build_yolo11_segmentation_numpy_array_from_host_pointer
)


__all__ = [
    "build_yolo11_classification_numpy_array_from_host_pointer",
    "resolve_yolo11_classification_numpy_dtype",
    "resolve_yolo11_classification_tensor_byte_size",
]
