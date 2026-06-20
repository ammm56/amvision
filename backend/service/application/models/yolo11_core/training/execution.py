"""YOLO11 detection 训练执行边界。"""

from __future__ import annotations

from backend.service.application.models.yolo11_core.training.plan import (
    Yolo11DetectionTrainingExecutionPlan,
    plan_yolo11_detection_training_execution,
)
from backend.service.application.models.yolo11_core.training.runtime import (
    Yolo11DetectionTrainingRuntime,
    build_yolo11_autocast_context,
    build_yolo11_detection_training_runtime,
    move_yolo11_optimizer_state_to_device,
)


YOLO11_DETECTION_CORE_IMPLEMENTATION_MODE = "yolo11-detection-core"


__all__ = [
    "YOLO11_DETECTION_CORE_IMPLEMENTATION_MODE",
    "Yolo11DetectionTrainingExecutionPlan",
    "Yolo11DetectionTrainingRuntime",
    "build_yolo11_autocast_context",
    "build_yolo11_detection_training_runtime",
    "move_yolo11_optimizer_state_to_device",
    "plan_yolo11_detection_training_execution",
]
