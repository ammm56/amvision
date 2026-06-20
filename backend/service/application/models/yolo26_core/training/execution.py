"""YOLO26 detection 训练执行边界。"""

from __future__ import annotations

from backend.service.application.models.yolo26_core.training.plan import (
    Yolo26DetectionTrainingExecutionPlan,
    plan_yolo26_detection_training_execution,
)
from backend.service.application.models.yolo26_core.training.runtime import (
    Yolo26DetectionTrainingRuntime,
    build_yolo26_autocast_context,
    build_yolo26_detection_training_runtime,
    move_yolo26_optimizer_state_to_device,
)


YOLO26_DETECTION_CORE_IMPLEMENTATION_MODE = "yolo26-detection-core"


__all__ = [
    "YOLO26_DETECTION_CORE_IMPLEMENTATION_MODE",
    "Yolo26DetectionTrainingExecutionPlan",
    "Yolo26DetectionTrainingRuntime",
    "build_yolo26_autocast_context",
    "build_yolo26_detection_training_runtime",
    "move_yolo26_optimizer_state_to_device",
    "plan_yolo26_detection_training_execution",
]
