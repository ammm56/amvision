"""YOLOv8 classification TensorRT runtime buffer 工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.detection.buffer import (
    build_yolov8_detection_numpy_array_from_host_pointer,
    resolve_yolov8_detection_numpy_dtype,
    resolve_yolov8_detection_tensor_byte_size,
)


resolve_yolov8_classification_numpy_dtype = resolve_yolov8_detection_numpy_dtype
resolve_yolov8_classification_tensor_byte_size = resolve_yolov8_detection_tensor_byte_size
build_yolov8_classification_numpy_array_from_host_pointer = (
    build_yolov8_detection_numpy_array_from_host_pointer
)


__all__ = [
    "build_yolov8_classification_numpy_array_from_host_pointer",
    "resolve_yolov8_classification_numpy_dtype",
    "resolve_yolov8_classification_tensor_byte_size",
]
