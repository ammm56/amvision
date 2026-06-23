"""YOLOv8 OBB 训练应用层入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.training.obb_execution import (
    YOLOV8_OBB_DEFAULT_EVALUATION_INTERVAL,
    YOLOV8_OBB_IMPLEMENTATION_MODE,
    YoloV8ObbTrainingBatchProgress,
    YoloV8ObbTrainingControlCommand,
    YoloV8ObbTrainingEpochProgress,
    YoloV8ObbTrainingExecutionRequest,
    YoloV8ObbTrainingExecutionResult,
    YoloV8ObbTrainingPausedError,
    YoloV8ObbTrainingSavePoint,
    YoloV8ObbTrainingTerminatedError,
    run_yolov8_obb_training,
)

__all__ = [
    "YOLOV8_OBB_DEFAULT_EVALUATION_INTERVAL",
    "YOLOV8_OBB_IMPLEMENTATION_MODE",
    "YoloV8ObbTrainingBatchProgress",
    "YoloV8ObbTrainingControlCommand",
    "YoloV8ObbTrainingEpochProgress",
    "YoloV8ObbTrainingExecutionRequest",
    "YoloV8ObbTrainingExecutionResult",
    "YoloV8ObbTrainingPausedError",
    "YoloV8ObbTrainingSavePoint",
    "YoloV8ObbTrainingTerminatedError",
    "run_yolov8_obb_training",
]
