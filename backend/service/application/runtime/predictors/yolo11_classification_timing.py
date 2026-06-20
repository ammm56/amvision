"""YOLO11 classification runtime 耗时统计工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo11_segmentation_timing import (
    is_yolo11_segmentation_debugger_attached,
    measure_yolo11_segmentation_cuda_event_elapsed_ms,
    measure_yolo11_segmentation_elapsed_ms,
    measure_yolo11_segmentation_stage_elapsed_ms,
    synchronize_yolo11_segmentation_device_for_timing,
)


is_yolo11_classification_debugger_attached = is_yolo11_segmentation_debugger_attached
measure_yolo11_classification_cuda_event_elapsed_ms = (
    measure_yolo11_segmentation_cuda_event_elapsed_ms
)
measure_yolo11_classification_elapsed_ms = measure_yolo11_segmentation_elapsed_ms
measure_yolo11_classification_stage_elapsed_ms = (
    measure_yolo11_segmentation_stage_elapsed_ms
)
synchronize_yolo11_classification_device_for_timing = (
    synchronize_yolo11_segmentation_device_for_timing
)


__all__ = [
    "is_yolo11_classification_debugger_attached",
    "measure_yolo11_classification_cuda_event_elapsed_ms",
    "measure_yolo11_classification_elapsed_ms",
    "measure_yolo11_classification_stage_elapsed_ms",
    "synchronize_yolo11_classification_device_for_timing",
]
