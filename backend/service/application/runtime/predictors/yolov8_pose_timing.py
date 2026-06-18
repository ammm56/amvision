"""YOLOv8 pose runtime 耗时统计工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolov8_detection_timing import (
    is_yolov8_detection_debugger_attached,
    measure_yolov8_detection_cuda_event_elapsed_ms,
    measure_yolov8_detection_elapsed_ms,
    measure_yolov8_detection_stage_elapsed_ms,
)


is_yolov8_pose_debugger_attached = is_yolov8_detection_debugger_attached
measure_yolov8_pose_cuda_event_elapsed_ms = measure_yolov8_detection_cuda_event_elapsed_ms
measure_yolov8_pose_elapsed_ms = measure_yolov8_detection_elapsed_ms
measure_yolov8_pose_stage_elapsed_ms = measure_yolov8_detection_stage_elapsed_ms


__all__ = [
    "is_yolov8_pose_debugger_attached",
    "measure_yolov8_pose_cuda_event_elapsed_ms",
    "measure_yolov8_pose_elapsed_ms",
    "measure_yolov8_pose_stage_elapsed_ms",
]
