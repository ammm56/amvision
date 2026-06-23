"""YOLOv8 训练执行入口。"""

from __future__ import annotations

from backend.service.application.models.yolov8_core.training.checkpoint import (
    YoloV8DetectionEpochCheckpointUpdate,
    build_yolov8_detection_checkpoint_state,
    build_yolov8_detection_epoch_checkpoint_update,
    decode_yolov8_detection_checkpoint_state,
    encode_yolov8_detection_checkpoint_state,
)
from backend.service.application.models.yolov8_core.training.control import (
    YoloV8DetectionEpochControlDecision,
    resolve_yolov8_detection_epoch_control,
)
from backend.service.application.models.yolov8_core.training.dataloader import (
    YoloV8DetectionTrainingDataloaderPlan,
    plan_yolov8_detection_training_dataloader,
)
from backend.service.application.models.yolov8_core.training.detection import (
    compute_yolov8_detection_training_loss,
    is_yolov8_detection_core_model,
)
from backend.service.application.models.yolov8_core.training.detection_execution import (
    YOLOV8_DETECTION_IMPLEMENTATION_MODE,
    YoloV8DetectionTrainingControlCommand,
    YoloV8DetectionTrainingEpochProgress,
    YoloV8DetectionTrainingExecutionRequest,
    YoloV8DetectionTrainingExecutionResult,
    YoloV8DetectionTrainingPausedError,
    YoloV8DetectionTrainingSavePoint,
    YoloV8DetectionTrainingTerminatedError,
    run_yolov8_detection_training,
)
from backend.service.application.models.yolov8_core.training.epoch import (
    YoloV8DetectionBestMetricUpdate,
    resolve_yolov8_detection_best_metric_name,
    resolve_yolov8_detection_best_metric_update,
    resolve_yolov8_detection_initial_best_metric_value,
    serialize_yolov8_detection_best_metric_value,
    should_run_yolov8_detection_validation,
)
from backend.service.application.models.yolov8_core.training.execution import (
    YoloV8DetectionTrainingDataContext,
    YoloV8DetectionTrainingExecutionPlan,
    plan_yolov8_detection_training_execution,
    prepare_yolov8_detection_training_data_context,
)
from backend.service.application.models.yolov8_core.training.runtime import (
    YoloV8DetectionTrainingRuntime,
    build_yolov8_autocast_context,
    build_yolov8_detection_training_runtime,
    move_yolov8_optimizer_state_to_device,
)
from backend.service.application.models.yolov8_core.training.runner import (
    YoloV8DetectionTrainingBatchProgress,
    YoloV8DetectionTrainingEpochResult,
    run_yolov8_detection_training_epoch,
)
from backend.service.application.models.yolov8_core.training.samples import (
    YoloV8DetectionTrainingSamplePlan,
    plan_yolov8_detection_training_samples,
)
from backend.service.application.models.yolov8_core.training.savepoint import (
    YoloV8DetectionTrainingSavepointPayload,
    build_yolov8_detection_training_savepoint_payload,
)
from backend.service.application.models.yolov8_core.training.resume import (
    YoloV8DetectionResumeValidationRequest,
    validate_yolov8_detection_resume_checkpoint,
)
from backend.service.application.models.yolov8_core.training.validation import (
    evaluate_yolov8_detection_validation_losses,
)

__all__ = [
    "YoloV8DetectionTrainingRuntime",
    "YOLOV8_DETECTION_IMPLEMENTATION_MODE",
    "YoloV8DetectionResumeValidationRequest",
    "YoloV8DetectionBestMetricUpdate",
    "YoloV8DetectionEpochControlDecision",
    "YoloV8DetectionEpochCheckpointUpdate",
    "YoloV8DetectionTrainingBatchProgress",
    "YoloV8DetectionTrainingControlCommand",
    "YoloV8DetectionTrainingDataContext",
    "YoloV8DetectionTrainingDataloaderPlan",
    "YoloV8DetectionTrainingEpochProgress",
    "YoloV8DetectionTrainingEpochResult",
    "YoloV8DetectionTrainingExecutionRequest",
    "YoloV8DetectionTrainingExecutionResult",
    "YoloV8DetectionTrainingExecutionPlan",
    "YoloV8DetectionTrainingPausedError",
    "YoloV8DetectionTrainingSamplePlan",
    "YoloV8DetectionTrainingSavePoint",
    "YoloV8DetectionTrainingSavepointPayload",
    "YoloV8DetectionTrainingTerminatedError",
    "build_yolov8_autocast_context",
    "build_yolov8_detection_checkpoint_state",
    "build_yolov8_detection_epoch_checkpoint_update",
    "build_yolov8_detection_training_runtime",
    "build_yolov8_detection_training_savepoint_payload",
    "compute_yolov8_detection_training_loss",
    "decode_yolov8_detection_checkpoint_state",
    "encode_yolov8_detection_checkpoint_state",
    "evaluate_yolov8_detection_validation_losses",
    "is_yolov8_detection_core_model",
    "move_yolov8_optimizer_state_to_device",
    "plan_yolov8_detection_training_dataloader",
    "plan_yolov8_detection_training_execution",
    "plan_yolov8_detection_training_samples",
    "prepare_yolov8_detection_training_data_context",
    "resolve_yolov8_detection_epoch_control",
    "resolve_yolov8_detection_best_metric_name",
    "resolve_yolov8_detection_best_metric_update",
    "resolve_yolov8_detection_initial_best_metric_value",
    "run_yolov8_detection_training_epoch",
    "run_yolov8_detection_training",
    "serialize_yolov8_detection_best_metric_value",
    "should_run_yolov8_detection_validation",
    "validate_yolov8_detection_resume_checkpoint",
]
