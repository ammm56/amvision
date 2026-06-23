"""YOLOv8 classification 训练应用层入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.training.classification_execution import (
    YOLOV8_CLASSIFICATION_DEFAULT_BATCH_SIZE,
    YOLOV8_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL,
    YOLOV8_CLASSIFICATION_DEFAULT_INPUT_SIZE,
    YOLOV8_CLASSIFICATION_DEFAULT_LR,
    YOLOV8_CLASSIFICATION_DEFAULT_MAX_EPOCHS,
    YOLOV8_CLASSIFICATION_DEFAULT_MIN_LR_RATIO,
    YOLOV8_CLASSIFICATION_DEFAULT_WEIGHT_DECAY,
    YOLOV8_CLASSIFICATION_IMPLEMENTATION_MODE,
    YoloV8ClassificationTrainingBatchProgress,
    YoloV8ClassificationTrainingControlCommand,
    YoloV8ClassificationTrainingEpochProgress,
    YoloV8ClassificationTrainingExecutionRequest,
    YoloV8ClassificationTrainingExecutionResult,
    YoloV8ClassificationTrainingPausedError,
    YoloV8ClassificationTrainingSavePoint,
    YoloV8ClassificationTrainingTerminatedError,
    run_yolov8_classification_training,
)

__all__ = [
    "YOLOV8_CLASSIFICATION_DEFAULT_BATCH_SIZE",
    "YOLOV8_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL",
    "YOLOV8_CLASSIFICATION_DEFAULT_INPUT_SIZE",
    "YOLOV8_CLASSIFICATION_DEFAULT_LR",
    "YOLOV8_CLASSIFICATION_DEFAULT_MAX_EPOCHS",
    "YOLOV8_CLASSIFICATION_DEFAULT_MIN_LR_RATIO",
    "YOLOV8_CLASSIFICATION_DEFAULT_WEIGHT_DECAY",
    "YOLOV8_CLASSIFICATION_IMPLEMENTATION_MODE",
    "YoloV8ClassificationTrainingBatchProgress",
    "YoloV8ClassificationTrainingControlCommand",
    "YoloV8ClassificationTrainingEpochProgress",
    "YoloV8ClassificationTrainingExecutionRequest",
    "YoloV8ClassificationTrainingExecutionResult",
    "YoloV8ClassificationTrainingPausedError",
    "YoloV8ClassificationTrainingSavePoint",
    "YoloV8ClassificationTrainingTerminatedError",
    "run_yolov8_classification_training",
]
