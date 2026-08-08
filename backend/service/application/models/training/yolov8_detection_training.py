"""YOLOv8 detection 训练应用层入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.training.detection_execution import (
    YOLOV8_DETECTION_IMPLEMENTATION_MODE,
    YoloV8DetectionTrainingExecutionRequest,
    YoloV8DetectionTrainingExecutionResult,
    YoloV8DetectionTrainingEpochProgress,
    YoloV8DetectionTrainingPausedError as CoreYoloV8DetectionTrainingPausedError,
    YoloV8DetectionTrainingTerminatedError as CoreYoloV8DetectionTrainingTerminatedError,
    run_yolov8_detection_training as run_yolov8_detection_training_core,
)
from backend.service.application.models.yolov8_core.training.runner import (
    YoloV8DetectionTrainingBatchProgress,
)
from backend.service.application.models.training.yolo_detection_training_control import (
    YoloDetectionTrainingPausedError,
    YoloDetectionTrainingSavePoint,
    YoloDetectionTrainingTerminatedError,
)

YOLOV8_IMPLEMENTATION_MODE = YOLOV8_DETECTION_IMPLEMENTATION_MODE
YoloV8TrainingBatchProgress = YoloV8DetectionTrainingBatchProgress
YoloV8TrainingEpochProgress = YoloV8DetectionTrainingEpochProgress


def run_yolov8_detection_training(
    request: YoloV8DetectionTrainingExecutionRequest,
) -> YoloV8DetectionTrainingExecutionResult:
    """执行 YOLOv8 detection 训练并统一平台控制异常类型。"""

    try:
        return run_yolov8_detection_training_core(request)
    except CoreYoloV8DetectionTrainingPausedError as error:
        raise YoloDetectionTrainingPausedError(
            YoloDetectionTrainingSavePoint(
                epoch=error.savepoint.epoch,
                latest_checkpoint_bytes=error.savepoint.latest_checkpoint_bytes,
                best_checkpoint_bytes=error.savepoint.best_checkpoint_bytes,
                best_metric_name=error.savepoint.best_metric_name,
                best_metric_value=error.savepoint.best_metric_value,
            )
        ) from error
    except CoreYoloV8DetectionTrainingTerminatedError as error:
        raise YoloDetectionTrainingTerminatedError() from error


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
