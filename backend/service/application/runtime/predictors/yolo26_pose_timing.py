"""YOLO26 pose runtime 耗时统计工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo_runtime_timing import (
    is_yolo_runtime_debugger_attached,
    measure_yolo_runtime_cuda_event_elapsed_ms,
    measure_yolo_runtime_elapsed_ms,
    measure_yolo_runtime_stage_elapsed_ms,
)


is_yolo26_pose_debugger_attached = is_yolo_runtime_debugger_attached
measure_yolo26_pose_cuda_event_elapsed_ms = measure_yolo_runtime_cuda_event_elapsed_ms
measure_yolo26_pose_elapsed_ms = measure_yolo_runtime_elapsed_ms
measure_yolo26_pose_stage_elapsed_ms = measure_yolo_runtime_stage_elapsed_ms


__all__ = [
    "is_yolo26_pose_debugger_attached",
    "measure_yolo26_pose_cuda_event_elapsed_ms",
    "measure_yolo26_pose_elapsed_ms",
    "measure_yolo26_pose_stage_elapsed_ms",
]
