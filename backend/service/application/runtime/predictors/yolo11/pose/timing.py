"""YOLO11 pose runtime 耗时统计工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8.detection.timing import (
    is_yolov8_detection_debugger_attached,
    measure_yolov8_detection_cuda_event_elapsed_ms,
    measure_yolov8_detection_elapsed_ms,
    measure_yolov8_detection_stage_elapsed_ms,
)


is_yolo11_pose_debugger_attached = is_yolov8_detection_debugger_attached
measure_yolo11_pose_cuda_event_elapsed_ms = (
    measure_yolov8_detection_cuda_event_elapsed_ms
)
measure_yolo11_pose_elapsed_ms = measure_yolov8_detection_elapsed_ms
measure_yolo11_pose_stage_elapsed_ms = measure_yolov8_detection_stage_elapsed_ms


__all__ = [
    "is_yolo11_pose_debugger_attached",
    "measure_yolo11_pose_cuda_event_elapsed_ms",
    "measure_yolo11_pose_elapsed_ms",
    "measure_yolo11_pose_stage_elapsed_ms",
]
