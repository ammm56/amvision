"""YOLOv8 classification runtime 耗时统计工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.detection.timing import (
    is_yolov8_detection_debugger_attached,
    measure_yolov8_detection_cuda_event_elapsed_ms,
    measure_yolov8_detection_elapsed_ms,
    measure_yolov8_detection_stage_elapsed_ms,
    synchronize_yolov8_detection_device_for_timing,
)


is_yolov8_classification_debugger_attached = is_yolov8_detection_debugger_attached
measure_yolov8_classification_cuda_event_elapsed_ms = measure_yolov8_detection_cuda_event_elapsed_ms
measure_yolov8_classification_elapsed_ms = measure_yolov8_detection_elapsed_ms
measure_yolov8_classification_stage_elapsed_ms = measure_yolov8_detection_stage_elapsed_ms
synchronize_yolov8_classification_device_for_timing = synchronize_yolov8_detection_device_for_timing


__all__ = [
    "is_yolov8_classification_debugger_attached",
    "measure_yolov8_classification_cuda_event_elapsed_ms",
    "measure_yolov8_classification_elapsed_ms",
    "measure_yolov8_classification_stage_elapsed_ms",
    "synchronize_yolov8_classification_device_for_timing",
]
