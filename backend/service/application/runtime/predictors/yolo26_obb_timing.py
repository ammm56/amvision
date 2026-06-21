"""YOLO26 OBB runtime 耗时统计工具。"""

from __future__ import annotations

from backend.service.application.runtime.predictors.yolo_runtime_timing import (
    is_yolo_runtime_debugger_attached,
    measure_yolo_runtime_cuda_event_elapsed_ms,
    measure_yolo_runtime_elapsed_ms,
    measure_yolo_runtime_stage_elapsed_ms,
    synchronize_yolo_runtime_device_for_timing,
)


is_yolo26_obb_debugger_attached = is_yolo_runtime_debugger_attached
measure_yolo26_obb_cuda_event_elapsed_ms = measure_yolo_runtime_cuda_event_elapsed_ms
measure_yolo26_obb_elapsed_ms = measure_yolo_runtime_elapsed_ms
measure_yolo26_obb_stage_elapsed_ms = measure_yolo_runtime_stage_elapsed_ms
synchronize_yolo26_obb_device_for_timing = synchronize_yolo_runtime_device_for_timing


__all__ = [
    "is_yolo26_obb_debugger_attached",
    "measure_yolo26_obb_cuda_event_elapsed_ms",
    "measure_yolo26_obb_elapsed_ms",
    "measure_yolo26_obb_stage_elapsed_ms",
    "synchronize_yolo26_obb_device_for_timing",
]
