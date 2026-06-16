"""YOLOX detection 训练应用入口。"""

from __future__ import annotations

from backend.service.application.models.yolox_core.cfg import (
    YOLOX_SCALE_PROFILES,
    YOLOX_SUPPORTED_MODEL_SCALES,
    YoloXScaleProfile,
)
from backend.service.application.models.yolox_core.training.execution import (
    YoloXDetectionTrainingExecutionRequest,
    YoloXDetectionTrainingExecutionResult,
    YoloXTrainingPausedError,
    YoloXTrainingTerminatedError,
    run_yolox_detection_training_execution,
)
from backend.service.application.models.yolox_core.training.trainer import (
    YOLOX_CORE_DEFAULT_EVALUATION_INTERVAL,
    YoloXTrainingBatchProgress,
    YoloXTrainingControlCommand,
    YoloXTrainingEpochProgress,
    YoloXTrainingSavePoint,
)

__all__ = [
    "YOLOX_CORE_DEFAULT_EVALUATION_INTERVAL",
    "YOLOX_SCALE_PROFILES",
    "YOLOX_SUPPORTED_MODEL_SCALES",
    "YoloXDetectionTrainingExecutionRequest",
    "YoloXDetectionTrainingExecutionResult",
    "YoloXScaleProfile",
    "YoloXTrainingBatchProgress",
    "YoloXTrainingControlCommand",
    "YoloXTrainingEpochProgress",
    "YoloXTrainingPausedError",
    "YoloXTrainingSavePoint",
    "YoloXTrainingTerminatedError",
    "run_yolox_detection_training",
]


def run_yolox_detection_training(
    request: YoloXDetectionTrainingExecutionRequest,
) -> YoloXDetectionTrainingExecutionResult:
    """执行一次 YOLOX detection 训练。

    应用层保留稳定调用入口，训练参数解析、数据链、验证评估和 checkpoint
    执行细节都在 yolox_core.training.execution 中维护。
    """

    return run_yolox_detection_training_execution(request)
