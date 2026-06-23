"""YOLOv8 detection 训练应用层入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.training.detection_execution import (
    YOLOV8_DETECTION_IMPLEMENTATION_MODE,
    YoloV8DetectionTrainingExecutionRequest,
    YoloV8DetectionTrainingExecutionResult,
    YoloV8DetectionTrainingEpochProgress,
    run_yolov8_detection_training,
)
from backend.service.application.models.yolov8_core.training.runner import (
    YoloV8DetectionTrainingBatchProgress,
)

YOLOV8_IMPLEMENTATION_MODE = YOLOV8_DETECTION_IMPLEMENTATION_MODE
YoloV8TrainingBatchProgress = YoloV8DetectionTrainingBatchProgress
YoloV8TrainingEpochProgress = YoloV8DetectionTrainingEpochProgress


__all__ = [
    "YOLOV8_IMPLEMENTATION_MODE",
    "YoloV8DetectionTrainingBatchProgress",
    "YoloV8DetectionTrainingEpochProgress",
    "YoloV8TrainingBatchProgress",
    "YoloV8TrainingEpochProgress",
    "YoloV8DetectionTrainingExecutionRequest",
    "YoloV8DetectionTrainingExecutionResult",
    "run_yolov8_detection_training",
]
