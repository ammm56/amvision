"""YOLO11 detection 训练执行模块。"""

from __future__ import annotations

from dataclasses import replace

from backend.service.application.models.yolo_primary_detection_training import (
    YoloPrimaryDetectionTrainingExecutionRequest as Yolo11DetectionTrainingExecutionRequest,
    YoloPrimaryDetectionTrainingExecutionResult as Yolo11DetectionTrainingExecutionResult,
    YoloPrimaryTrainingBatchProgress as Yolo11TrainingBatchProgress,
    YoloPrimaryTrainingEpochProgress as Yolo11TrainingEpochProgress,
    run_yolo_primary_detection_training,
)


YOLO11_BOOTSTRAP_IMPLEMENTATION_MODE = "yolo11-detection"


def run_yolo11_detection_training(
    request: Yolo11DetectionTrainingExecutionRequest,
) -> Yolo11DetectionTrainingExecutionResult:
    """执行一轮项目内 YOLO11 detection 训练。"""

    return run_yolo_primary_detection_training(
        replace(
            request,
            model_type="yolo11",
            implementation_mode=YOLO11_BOOTSTRAP_IMPLEMENTATION_MODE,
        )
    )
