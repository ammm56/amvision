"""YOLOv8 pose 训练应用层入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.training.pose_execution import (
    YOLOV8_POSE_DEFAULT_EVALUATION_INTERVAL,
    YOLOV8_POSE_IMPLEMENTATION_MODE,
    YoloV8PoseTrainingBatchProgress,
    YoloV8PoseTrainingControlCommand,
    YoloV8PoseTrainingEpochProgress,
    YoloV8PoseTrainingExecutionRequest,
    YoloV8PoseTrainingExecutionResult,
    YoloV8PoseTrainingPausedError,
    YoloV8PoseTrainingSavePoint,
    YoloV8PoseTrainingTerminatedError,
    run_yolov8_pose_training,
)

__all__ = [
    "YOLOV8_POSE_DEFAULT_EVALUATION_INTERVAL",
    "YOLOV8_POSE_IMPLEMENTATION_MODE",
    "YoloV8PoseTrainingBatchProgress",
    "YoloV8PoseTrainingControlCommand",
    "YoloV8PoseTrainingEpochProgress",
    "YoloV8PoseTrainingExecutionRequest",
    "YoloV8PoseTrainingExecutionResult",
    "YoloV8PoseTrainingPausedError",
    "YoloV8PoseTrainingSavePoint",
    "YoloV8PoseTrainingTerminatedError",
    "run_yolov8_pose_training",
]
