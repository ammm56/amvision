"""YOLO11 OBB runtime 耗时统计工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8_segmentation_timing import (
    is_yolov8_segmentation_debugger_attached,
    measure_yolov8_segmentation_cuda_event_elapsed_ms,
    measure_yolov8_segmentation_elapsed_ms,
    measure_yolov8_segmentation_stage_elapsed_ms,
    synchronize_yolov8_segmentation_device_for_timing,
)


is_yolo11_obb_debugger_attached = is_yolov8_segmentation_debugger_attached
measure_yolo11_obb_cuda_event_elapsed_ms = (
    measure_yolov8_segmentation_cuda_event_elapsed_ms
)
measure_yolo11_obb_elapsed_ms = measure_yolov8_segmentation_elapsed_ms
measure_yolo11_obb_stage_elapsed_ms = measure_yolov8_segmentation_stage_elapsed_ms
synchronize_yolo11_obb_device_for_timing = (
    synchronize_yolov8_segmentation_device_for_timing
)


__all__ = [
    "is_yolo11_obb_debugger_attached",
    "measure_yolo11_obb_cuda_event_elapsed_ms",
    "measure_yolo11_obb_elapsed_ms",
    "measure_yolo11_obb_stage_elapsed_ms",
    "synchronize_yolo11_obb_device_for_timing",
]
