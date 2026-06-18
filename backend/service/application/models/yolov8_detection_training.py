"""YOLOv8 detection 训练执行模块。"""

from __future__ import annotations

from backend.service.application.models.yolo_primary_detection_training import (
    YoloPrimaryDetectionTrainingExecutionRequest as YoloV8DetectionTrainingExecutionRequest,
    YoloPrimaryDetectionTrainingExecutionResult as YoloV8DetectionTrainingExecutionResult,
    YoloPrimaryTrainingBatchProgress as YoloV8TrainingBatchProgress,
    YoloPrimaryTrainingEpochProgress as YoloV8TrainingEpochProgress,
    run_yolo_primary_detection_training,
)

YOLOV8_IMPLEMENTATION_MODE = "yolov8-detection-core"
run_yolov8_detection_training = run_yolo_primary_detection_training


__all__ = [
    "YOLOV8_IMPLEMENTATION_MODE",
    "YoloV8TrainingBatchProgress",
    "YoloV8TrainingEpochProgress",
    "YoloV8DetectionTrainingExecutionRequest",
    "YoloV8DetectionTrainingExecutionResult",
    "run_yolov8_detection_training",
]
