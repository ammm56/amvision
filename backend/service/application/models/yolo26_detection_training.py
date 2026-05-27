"""YOLO26 detection bootstrap 训练执行模块。"""

from __future__ import annotations

from dataclasses import replace

from backend.service.application.models.yolo_primary_detection_training import (
    YoloPrimaryDetectionTrainingExecutionRequest as Yolo26DetectionTrainingExecutionRequest,
    YoloPrimaryDetectionTrainingExecutionResult as Yolo26DetectionTrainingExecutionResult,
    YoloPrimaryTrainingBatchProgress as Yolo26TrainingBatchProgress,
    YoloPrimaryTrainingEpochProgress as Yolo26TrainingEpochProgress,
    run_yolo_primary_detection_training,
)


YOLO26_BOOTSTRAP_IMPLEMENTATION_MODE = "yolo26-detection-bootstrap"


def run_yolo26_detection_training(
    request: Yolo26DetectionTrainingExecutionRequest,
) -> Yolo26DetectionTrainingExecutionResult:
    """执行一轮项目内 YOLO26 detection bootstrap 训练。"""

    return run_yolo_primary_detection_training(
        replace(
            request,
            model_type="yolo26",
            implementation_mode=YOLO26_BOOTSTRAP_IMPLEMENTATION_MODE,
        )
    )
