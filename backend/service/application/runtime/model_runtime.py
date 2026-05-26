"""模型运行时稳定边界定义。"""

from __future__ import annotations

from backend.service.application.runtime.detection_model_runtime import (
    DefaultDetectionModelRuntime,
    DefaultYoloXModelRuntime,
    DetectionModelRuntime,
    DetectionModelRuntimeSession,
)


# 兼容旧模块导出的类型别名。
ModelRuntimeSession = DetectionModelRuntimeSession
ModelRuntime = DetectionModelRuntime


__all__ = [
    "DefaultDetectionModelRuntime",
    "DefaultYoloXModelRuntime",
    "DetectionModelRuntime",
    "DetectionModelRuntimeSession",
    "ModelRuntime",
    "ModelRuntimeSession",
]
