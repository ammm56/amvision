"""YOLOv8 segmentation 训练应用层入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.training.segmentation_execution import (
    YOLOV8_SEGMENTATION_IMPLEMENTATION_MODE,
    YoloV8SegmentationTrainingBatchProgress,
    YoloV8SegmentationTrainingControlCommand,
    YoloV8SegmentationTrainingEpochProgress,
    YoloV8SegmentationTrainingExecutionRequest,
    YoloV8SegmentationTrainingExecutionResult,
    YoloV8SegmentationTrainingPausedError,
    YoloV8SegmentationTrainingSavePoint,
    YoloV8SegmentationTrainingTerminatedError,
    run_yolov8_segmentation_training,
)

__all__ = [
    "YOLOV8_SEGMENTATION_IMPLEMENTATION_MODE",
    "YoloV8SegmentationTrainingBatchProgress",
    "YoloV8SegmentationTrainingControlCommand",
    "YoloV8SegmentationTrainingEpochProgress",
    "YoloV8SegmentationTrainingExecutionRequest",
    "YoloV8SegmentationTrainingExecutionResult",
    "YoloV8SegmentationTrainingPausedError",
    "YoloV8SegmentationTrainingSavePoint",
    "YoloV8SegmentationTrainingTerminatedError",
    "run_yolov8_segmentation_training",
]
