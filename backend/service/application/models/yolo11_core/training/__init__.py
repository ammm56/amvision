"""YOLO11 训练执行入口。"""

from __future__ import annotations

from backend.service.application.models.yolo11_core.training.detection import (
    compute_yolo11_detection_training_loss,
    is_yolo11_detection_core_model,
)
from backend.service.application.models.yolo11_core.training.detection_support import (
    YOLO11_DETECTION_DEFAULT_ASSIGN_ALPHA,
    YOLO11_DETECTION_DEFAULT_ASSIGN_BETA,
    YOLO11_DETECTION_DEFAULT_ASSIGN_TOPK,
    YOLO11_DETECTION_DEFAULT_BATCH_SIZE,
    YOLO11_DETECTION_DEFAULT_BOX_LOSS_WEIGHT,
    YOLO11_DETECTION_DEFAULT_CLASS_LOSS_WEIGHT,
    YOLO11_DETECTION_DEFAULT_DFL_LOSS_WEIGHT,
    YOLO11_DETECTION_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
    YOLO11_DETECTION_DEFAULT_EVAL_NMS_THRESHOLD,
    YOLO11_DETECTION_DEFAULT_EVALUATION_INTERVAL,
    YOLO11_DETECTION_DEFAULT_GRAD_CLIP_NORM,
    YOLO11_DETECTION_DEFAULT_INPUT_SIZE,
    YOLO11_DETECTION_DEFAULT_MAX_EPOCHS,
    YOLO11_DETECTION_DEFAULT_MIN_LR_RATIO,
    Yolo11DetectionTrainingImports,
    read_yolo11_float_option,
    read_yolo11_int_option,
    require_yolo11_detection_training_imports,
    resolve_yolo11_detection_input_size,
    resolve_yolo11_detection_runtime,
    unwrap_yolo11_detection_outputs,
)
from backend.service.application.models.yolo11_core.training.checkpoint import (
    Yolo11DetectionEpochCheckpointUpdate,
    build_yolo11_detection_checkpoint_state,
    build_yolo11_detection_epoch_checkpoint_update,
    decode_yolo11_detection_checkpoint_state,
    encode_yolo11_detection_checkpoint_state,
)
from backend.service.application.models.yolo11_core.training.classification_checkpoint import (
    Yolo11ClassificationResumeState,
    build_yolo11_classification_checkpoint_bytes,
    load_yolo11_classification_model_state,
    load_yolo11_classification_resume_state,
    validate_yolo11_classification_resume_parameters,
)
from backend.service.application.models.yolo11_core.training.classification_defaults import (
    YOLO11_CLASSIFICATION_DEFAULT_INPUT_SIZE,
    YOLO11_CLASSIFICATION_DEFAULT_LR,
    YOLO11_CLASSIFICATION_DEFAULT_MIN_LR_RATIO,
    YOLO11_CLASSIFICATION_DEFAULT_WEIGHT_DECAY,
)
from backend.service.application.models.yolo11_core.training.classification_imports import (
    Yolo11ClassificationTrainingImports,
    require_yolo11_classification_training_imports,
)
from backend.service.application.models.yolo11_core.training.classification_runtime import (
    Yolo11ClassificationTrainingRuntime,
    build_yolo11_classification_autocast_context,
    build_yolo11_classification_training_runtime,
    move_yolo11_classification_optimizer_state_to_device,
    resolve_yolo11_classification_training_device,
)
from backend.service.application.models.yolo11_core.training.classification_trainer import (
    Yolo11ClassificationTrainingControlCommand,
    Yolo11ClassificationTrainingEpochProgress,
    Yolo11ClassificationTrainingLoopResult,
    Yolo11ClassificationTrainingPausedError,
    Yolo11ClassificationTrainingSavePoint,
    Yolo11ClassificationTrainingTerminatedError,
    run_yolo11_classification_training_loop,
)
from backend.service.application.models.yolo11_core.training.segmentation_anchors import (
    build_yolo11_segmentation_anchors_from_features,
)
from backend.service.application.models.yolo11_core.training.segmentation_checkpoint import (
    Yolo11SegmentationResumeState,
    build_yolo11_segmentation_checkpoint_bytes,
    load_yolo11_segmentation_model_state,
    load_yolo11_segmentation_resume_state,
    restore_yolo11_segmentation_training_state,
    validate_yolo11_segmentation_resume_parameters,
)
from backend.service.application.models.yolo11_core.training.segmentation_imports import (
    Yolo11SegmentationTrainingImports,
    build_yolo11_segmentation_autocast_context,
    require_yolo11_segmentation_training_imports,
    resolve_yolo11_segmentation_training_device,
)
from backend.service.application.models.yolo11_core.training.segmentation_manifest import (
    Yolo11SegmentationTrainingAnnotation,
    Yolo11SegmentationTrainingManifest,
    load_yolo11_segmentation_training_manifest,
)
from backend.service.application.models.yolo11_core.training.pose_checkpoint import (
    Yolo11PoseResumeState,
    build_yolo11_pose_checkpoint_bytes,
    load_yolo11_pose_resume_state,
    restore_yolo11_pose_training_state,
    validate_yolo11_pose_resume_parameters,
)
from backend.service.application.models.yolo11_core.training.pose_imports import (
    Yolo11PoseTrainingImports,
    build_yolo11_pose_autocast_context,
    require_yolo11_pose_training_imports,
    resolve_yolo11_pose_training_device,
)
from backend.service.application.models.yolo11_core.training.pose_manifest import (
    Yolo11PoseTrainingAnnotation,
    Yolo11PoseTrainingManifest,
    load_yolo11_pose_training_manifest,
)
from backend.service.application.models.yolo11_core.training.pose_trainer import (
    Yolo11PoseTrainingControlCommand,
    Yolo11PoseTrainingEpochProgress,
    Yolo11PoseTrainingLoopResult,
    Yolo11PoseTrainingPausedError,
    Yolo11PoseTrainingSavePoint,
    Yolo11PoseTrainingTerminatedError,
    run_yolo11_pose_training_loop,
)
from backend.service.application.models.yolo11_core.training.obb_checkpoint import (
    Yolo11ObbResumeState,
    build_yolo11_obb_checkpoint_bytes,
    load_yolo11_obb_resume_state,
    restore_yolo11_obb_training_state,
    validate_yolo11_obb_resume_parameters,
)
from backend.service.application.models.yolo11_core.training.obb_imports import (
    Yolo11ObbTrainingImports,
    build_yolo11_obb_autocast_context,
    require_yolo11_obb_training_imports,
    resolve_yolo11_obb_training_device,
)
from backend.service.application.models.yolo11_core.training.obb_manifest import (
    Yolo11ObbTrainingAnnotation,
    Yolo11ObbTrainingManifest,
    load_yolo11_obb_training_manifest,
)
from backend.service.application.models.yolo11_core.training.obb_trainer import (
    Yolo11ObbTrainingControlCommand,
    Yolo11ObbTrainingEpochProgress,
    Yolo11ObbTrainingLoopResult,
    Yolo11ObbTrainingPausedError,
    Yolo11ObbTrainingSavePoint,
    Yolo11ObbTrainingTerminatedError,
    run_yolo11_obb_training_loop,
)
from backend.service.application.models.yolo11_core.training.control import (
    Yolo11DetectionEpochControlDecision,
    resolve_yolo11_detection_epoch_control,
)
from backend.service.application.models.yolo11_core.training.data_context import (
    Yolo11DetectionTrainingDataContext,
    prepare_yolo11_detection_training_data_context,
)
from backend.service.application.models.yolo11_core.training.epoch import (
    resolve_yolo11_detection_best_metric_name,
    resolve_yolo11_detection_best_metric_update,
    resolve_yolo11_detection_initial_best_metric_value,
    serialize_yolo11_detection_best_metric_value,
    should_run_yolo11_detection_validation,
)
from backend.service.application.models.yolo11_core.training.plan import (
    Yolo11DetectionTrainingExecutionPlan,
    plan_yolo11_detection_training_execution,
)
from backend.service.application.models.yolo11_core.training.runner import (
    Yolo11DetectionTrainingBatchProgress,
    Yolo11DetectionTrainingEpochResult,
    run_yolo11_detection_training_epoch,
)
from backend.service.application.models.yolo11_core.training.resume import (
    Yolo11DetectionResumeValidationRequest,
    validate_yolo11_detection_resume_checkpoint,
)
from backend.service.application.models.yolo11_core.training.runtime import (
    Yolo11DetectionTrainingRuntime,
    build_yolo11_autocast_context,
    build_yolo11_detection_training_runtime,
    move_yolo11_optimizer_state_to_device,
)
from backend.service.application.models.yolo11_core.training.savepoint import (
    Yolo11DetectionTrainingSavepointPayload,
    build_yolo11_detection_training_savepoint_payload,
)
from backend.service.application.models.yolo11_core.training.trainer import (
    Yolo11DetectionTrainerEpochProgress,
    Yolo11DetectionTrainingLoopResult,
    Yolo11DetectionTrainingPausedError,
    Yolo11DetectionTrainingTerminatedError,
    run_yolo11_detection_training_loop,
)
from backend.service.application.models.yolo11_core.training.validation import (
    evaluate_yolo11_detection_validation_losses,
)

__all__ = [
    "YOLO11_CLASSIFICATION_DEFAULT_INPUT_SIZE",
    "YOLO11_CLASSIFICATION_DEFAULT_LR",
    "YOLO11_CLASSIFICATION_DEFAULT_MIN_LR_RATIO",
    "YOLO11_CLASSIFICATION_DEFAULT_WEIGHT_DECAY",
    "YOLO11_DETECTION_DEFAULT_ASSIGN_ALPHA",
    "YOLO11_DETECTION_DEFAULT_ASSIGN_BETA",
    "YOLO11_DETECTION_DEFAULT_ASSIGN_TOPK",
    "YOLO11_DETECTION_DEFAULT_BATCH_SIZE",
    "YOLO11_DETECTION_DEFAULT_BOX_LOSS_WEIGHT",
    "YOLO11_DETECTION_DEFAULT_CLASS_LOSS_WEIGHT",
    "YOLO11_DETECTION_DEFAULT_DFL_LOSS_WEIGHT",
    "YOLO11_DETECTION_DEFAULT_EVAL_CONFIDENCE_THRESHOLD",
    "YOLO11_DETECTION_DEFAULT_EVAL_NMS_THRESHOLD",
    "YOLO11_DETECTION_DEFAULT_EVALUATION_INTERVAL",
    "YOLO11_DETECTION_DEFAULT_GRAD_CLIP_NORM",
    "YOLO11_DETECTION_DEFAULT_INPUT_SIZE",
    "YOLO11_DETECTION_DEFAULT_MAX_EPOCHS",
    "YOLO11_DETECTION_DEFAULT_MIN_LR_RATIO",
    "Yolo11DetectionEpochControlDecision",
    "Yolo11DetectionEpochCheckpointUpdate",
    "Yolo11ClassificationResumeState",
    "Yolo11ClassificationTrainingControlCommand",
    "Yolo11ClassificationTrainingEpochProgress",
    "Yolo11ClassificationTrainingImports",
    "Yolo11ClassificationTrainingLoopResult",
    "Yolo11ClassificationTrainingPausedError",
    "Yolo11ClassificationTrainingRuntime",
    "Yolo11ClassificationTrainingSavePoint",
    "Yolo11ClassificationTrainingTerminatedError",
    "Yolo11SegmentationResumeState",
    "Yolo11SegmentationTrainingAnnotation",
    "Yolo11SegmentationTrainingImports",
    "Yolo11SegmentationTrainingManifest",
    "Yolo11PoseResumeState",
    "Yolo11PoseTrainingAnnotation",
    "Yolo11PoseTrainingControlCommand",
    "Yolo11PoseTrainingEpochProgress",
    "Yolo11PoseTrainingImports",
    "Yolo11PoseTrainingLoopResult",
    "Yolo11PoseTrainingManifest",
    "Yolo11PoseTrainingPausedError",
    "Yolo11PoseTrainingSavePoint",
    "Yolo11PoseTrainingTerminatedError",
    "Yolo11ObbResumeState",
    "Yolo11ObbTrainingAnnotation",
    "Yolo11ObbTrainingControlCommand",
    "Yolo11ObbTrainingEpochProgress",
    "Yolo11ObbTrainingImports",
    "Yolo11ObbTrainingLoopResult",
    "Yolo11ObbTrainingManifest",
    "Yolo11ObbTrainingPausedError",
    "Yolo11ObbTrainingSavePoint",
    "Yolo11ObbTrainingTerminatedError",
    "Yolo11DetectionResumeValidationRequest",
    "Yolo11DetectionTrainingBatchProgress",
    "Yolo11DetectionTrainingDataContext",
    "Yolo11DetectionTrainingEpochResult",
    "Yolo11DetectionTrainingExecutionPlan",
    "Yolo11DetectionTrainingImports",
    "Yolo11DetectionTrainerEpochProgress",
    "Yolo11DetectionTrainingLoopResult",
    "Yolo11DetectionTrainingPausedError",
    "Yolo11DetectionTrainingRuntime",
    "Yolo11DetectionTrainingSavepointPayload",
    "Yolo11DetectionTrainingTerminatedError",
    "build_yolo11_autocast_context",
    "build_yolo11_classification_autocast_context",
    "build_yolo11_classification_checkpoint_bytes",
    "build_yolo11_classification_training_runtime",
    "build_yolo11_segmentation_anchors_from_features",
    "build_yolo11_segmentation_autocast_context",
    "build_yolo11_segmentation_checkpoint_bytes",
    "build_yolo11_pose_autocast_context",
    "build_yolo11_pose_checkpoint_bytes",
    "build_yolo11_obb_autocast_context",
    "build_yolo11_obb_checkpoint_bytes",
    "build_yolo11_detection_checkpoint_state",
    "build_yolo11_detection_epoch_checkpoint_update",
    "build_yolo11_detection_training_runtime",
    "build_yolo11_detection_training_savepoint_payload",
    "compute_yolo11_detection_training_loss",
    "decode_yolo11_detection_checkpoint_state",
    "encode_yolo11_detection_checkpoint_state",
    "evaluate_yolo11_detection_validation_losses",
    "is_yolo11_detection_core_model",
    "load_yolo11_classification_model_state",
    "load_yolo11_classification_resume_state",
    "load_yolo11_segmentation_model_state",
    "load_yolo11_segmentation_resume_state",
    "load_yolo11_segmentation_training_manifest",
    "load_yolo11_pose_resume_state",
    "load_yolo11_pose_training_manifest",
    "load_yolo11_obb_resume_state",
    "load_yolo11_obb_training_manifest",
    "move_yolo11_classification_optimizer_state_to_device",
    "move_yolo11_optimizer_state_to_device",
    "plan_yolo11_detection_training_execution",
    "prepare_yolo11_detection_training_data_context",
    "read_yolo11_float_option",
    "read_yolo11_int_option",
    "resolve_yolo11_classification_training_device",
    "resolve_yolo11_detection_best_metric_name",
    "resolve_yolo11_detection_best_metric_update",
    "resolve_yolo11_detection_initial_best_metric_value",
    "run_yolo11_detection_training_epoch",
    "run_yolo11_detection_training_loop",
    "run_yolo11_classification_training_loop",
    "run_yolo11_pose_training_loop",
    "run_yolo11_obb_training_loop",
    "require_yolo11_classification_training_imports",
    "require_yolo11_detection_training_imports",
    "require_yolo11_segmentation_training_imports",
    "require_yolo11_pose_training_imports",
    "require_yolo11_obb_training_imports",
    "resolve_yolo11_segmentation_training_device",
    "resolve_yolo11_pose_training_device",
    "resolve_yolo11_obb_training_device",
    "resolve_yolo11_detection_input_size",
    "resolve_yolo11_detection_runtime",
    "restore_yolo11_segmentation_training_state",
    "restore_yolo11_pose_training_state",
    "restore_yolo11_obb_training_state",
    "serialize_yolo11_detection_best_metric_value",
    "should_run_yolo11_detection_validation",
    "resolve_yolo11_detection_epoch_control",
    "unwrap_yolo11_detection_outputs",
    "validate_yolo11_detection_resume_checkpoint",
    "validate_yolo11_classification_resume_parameters",
    "validate_yolo11_segmentation_resume_parameters",
    "validate_yolo11_pose_resume_parameters",
    "validate_yolo11_obb_resume_parameters",
]
