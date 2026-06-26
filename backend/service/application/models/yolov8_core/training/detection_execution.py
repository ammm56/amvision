"""YOLOv8 detection 训练执行入口。"""

from __future__ import annotations

import io
import math
import random
from collections.abc import Callable
from contextlib import nullcontext, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.postprocess.detection_postprocess import (
    DETECTION_POSTPROCESS_MODE_NMS,
    postprocess_detection_prediction_array,
)
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_detection_training_batch,
)
from backend.service.application.models.yolov8_core.training.checkpoint import (
    build_yolov8_detection_epoch_checkpoint_update,
    encode_yolov8_detection_checkpoint_state,
)
from backend.service.application.models.yolov8_core.training.control import (
    resolve_yolov8_detection_epoch_control,
)
from backend.service.application.models.yolov8_core.training.detection import (
    compute_yolov8_detection_training_loss,
    is_yolov8_detection_core_model,
)
from backend.service.application.models.yolov8_core.training.epoch import (
    resolve_yolov8_detection_best_metric_update,
    serialize_yolov8_detection_best_metric_value,
    should_run_yolov8_detection_validation,
)
from backend.service.application.models.yolov8_core.training.execution import (
    plan_yolov8_detection_training_execution,
    prepare_yolov8_detection_training_data_context,
)
from backend.service.application.models.yolov8_core.training.resume import (
    YoloV8DetectionResumeValidationRequest,
    validate_yolov8_detection_resume_checkpoint,
)
from backend.service.application.models.yolov8_core.training.runner import (
    YoloV8DetectionTrainingBatchProgress,
    run_yolov8_detection_training_epoch,
)
from backend.service.application.models.yolov8_core.training.runtime import (
    build_yolov8_detection_training_runtime,
    move_yolov8_optimizer_state_to_device,
)
from backend.service.application.models.yolov8_core.training.savepoint import (
    build_yolov8_detection_training_savepoint_payload,
)
from backend.service.application.models.yolov8_core.training.validation import (
    evaluate_yolov8_detection_validation_losses,
)
from backend.service.application.models.yolo_core_common.modeling.detection_builder import (
    load_yolo_checkpoint,
)
from backend.service.application.models.yolov8_core import (
    build_yolov8_model,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLOV8_DETECTION_IMPLEMENTATION_MODE = "yolov8-detection-core"
YOLOV8_DETECTION_DEFAULT_INPUT_SIZE = (640, 640)
YOLOV8_DETECTION_DEFAULT_BATCH_SIZE = 1
YOLOV8_DETECTION_DEFAULT_MAX_EPOCHS = 1
YOLOV8_DETECTION_DEFAULT_EVALUATION_INTERVAL = 5
YOLOV8_DETECTION_DEFAULT_EVAL_CONFIDENCE_THRESHOLD = 0.001
YOLOV8_DETECTION_DEFAULT_EVAL_NMS_THRESHOLD = 0.7
YOLOV8_DETECTION_DEFAULT_ASSIGN_TOPK = 10
YOLOV8_DETECTION_DEFAULT_CLASS_LOSS_WEIGHT = 0.5
YOLOV8_DETECTION_DEFAULT_BOX_LOSS_WEIGHT = 7.5
YOLOV8_DETECTION_DEFAULT_DFL_LOSS_WEIGHT = 1.5
YOLOV8_DETECTION_DEFAULT_ASSIGN_ALPHA = 0.5
YOLOV8_DETECTION_DEFAULT_ASSIGN_BETA = 6.0
YOLOV8_DETECTION_DEFAULT_MIN_LR_RATIO = 0.01
YOLOV8_DETECTION_DEFAULT_GRAD_CLIP_NORM = 10.0
YOLOV8_DETECTION_DEFAULT_FLIP_PROB = 0.5
YOLOV8_DETECTION_DEFAULT_HSV_PROB = 1.0
YOLOV8_DETECTION_DEFAULT_MOSAIC_PROB = 1.0
YOLOV8_DETECTION_DEFAULT_MIXUP_PROB = 0.0
YOLOV8_DETECTION_DEFAULT_ENABLE_MIXUP = True
YOLOV8_DETECTION_DEFAULT_AFFINE_PROB = 1.0
YOLOV8_DETECTION_DEFAULT_AFFINE_DEGREES = 0.0
YOLOV8_DETECTION_DEFAULT_AFFINE_TRANSLATE = 0.1
YOLOV8_DETECTION_DEFAULT_AFFINE_SCALE = 0.5
YOLOV8_DETECTION_DEFAULT_AFFINE_SHEAR = 0.0
YOLOV8_DETECTION_DEFAULT_AFFINE_PERSPECTIVE = 0.0
YOLOV8_DETECTION_DEFAULT_MOSAIC_SCALE = (0.5, 1.5)
YOLOV8_DETECTION_DEFAULT_MIXUP_SCALE = (0.5, 1.5)
YOLOV8_DETECTION_DEFAULT_CLOSE_MOSAIC_EPOCHS = 10
YOLOV8_DETECTION_DEFAULT_MULTI_SCALE = False
YOLOV8_DETECTION_DEFAULT_MULTI_SCALE_RANGE = (0.5, 1.5)
YOLOV8_DETECTION_DEFAULT_MULTI_SCALE_STRIDE = 32


@dataclass(frozen=True)
class YoloV8DetectionTrainingEpochProgress:
    """描述单轮训练结束后的进度快照。"""

    epoch: int
    max_epochs: int
    evaluation_interval: int
    validation_ran: bool
    evaluated_epochs: tuple[int, ...]
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_snapshot: dict[str, object] | None
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float | None


@dataclass(frozen=True)
class YoloV8DetectionTrainingControlCommand:
    """描述单轮训练结束后由上层返回给训练循环的控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class YoloV8DetectionTrainingSavePoint:
    """描述训练在某个 epoch 边界导出的可恢复 savepoint。"""

    epoch: int
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None = None
    best_metric_name: str = ""
    best_metric_value: float | None = None


@dataclass(frozen=True)
class YoloV8DetectionTrainingExecutionRequest:
    """描述一次 YOLOv8 detection 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str
    model_type: str = "yolov8"
    implementation_mode: str = YOLOV8_DETECTION_IMPLEMENTATION_MODE
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    warm_start_checkpoint_path: Path | None = None
    resume_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] | None = None
    batch_callback: Callable[[YoloV8DetectionTrainingBatchProgress], None] | None = None
    epoch_callback: (
        Callable[
            [YoloV8DetectionTrainingEpochProgress], YoloV8DetectionTrainingControlCommand | None
        ]
        | None
    ) = None
    savepoint_callback: Callable[[YoloV8DetectionTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class YoloV8DetectionTrainingExecutionResult:
    """描述一次 YOLOv8 detection 训练执行结果。"""

    checkpoint_bytes: bytes
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    warm_start_summary: dict[str, object]
    implementation_mode: str
    best_metric_name: str
    best_metric_value: float
    evaluation_interval: int
    category_names: tuple[str, ...]
    split_names: tuple[str, ...]
    sample_count: int
    train_sample_count: int
    input_size: tuple[int, int]
    batch_size: int
    max_epochs: int
    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str
    precision: str
    validation_split_name: str | None
    validation_sample_count: int
    parameter_count: int


@dataclass(frozen=True)
class _TrainingImports:
    """描述 YOLOv8 detection 训练所需的第三方依赖对象。"""

    cv2: Any
    np: Any
    torch: Any
    COCO: Any | None
    COCOeval: Any | None


@dataclass(frozen=True)
class _ResolvedDetectionSplit:
    """描述一个已经解析完成的 detection split。"""

    name: str
    image_root: Path
    sample_count: int
    annotation_payload: dict[str, object]
    annotation_file: Path | None = None


@dataclass(frozen=True)
class _ResolvedTrainingSample:
    """描述一个训练样本及其完整检测标注。"""

    image_id: int
    image_path: Path
    image_width: int
    image_height: int
    annotations: tuple["_ResolvedTrainingAnnotation", ...]


@dataclass(frozen=True)
class _ResolvedTrainingAnnotation:
    """描述单个检测目标的原图 bbox 与类别。"""

    category_index: int
    category_id: int
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class _PreparedTrainingTarget:
    """描述单张图片在当前训练输入尺寸下的目标。"""

    image_id: int
    image_width: int
    image_height: int
    boxes_xyxy: tuple[tuple[float, float, float, float], ...]
    category_indexes: tuple[int, ...]


@dataclass(frozen=True)
class _DetectionAugmentationOptions:
    """描述 detection 训练阶段启用的数据增强参数。"""

    flip_prob: float
    hsv_prob: float
    mosaic_prob: float
    mixup_prob: float
    enable_mixup: bool
    affine_prob: float
    degrees: float
    translate: float
    scale: float
    shear: float
    perspective: float
    mosaic_scale: tuple[float, float]
    mixup_scale: tuple[float, float]
    close_mosaic_epochs: int
    multi_scale: bool
    multi_scale_range: tuple[float, float]
    multi_scale_stride: int


@dataclass(frozen=True)
class _LoadedResumeState:
    """描述从 latest checkpoint 解析出的恢复训练状态。"""

    resume_epoch: int
    epoch_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    evaluated_epochs: tuple[int, ...]
    best_metric_name: str
    best_metric_value: float | None
    best_checkpoint_state: dict[str, object] | None
    warm_start_summary: dict[str, object]


class YoloV8DetectionTrainingPausedError(Exception):
    """表示训练在 epoch 边界按请求完成保存后进入 paused 状态。"""

    def __init__(self, savepoint: YoloV8DetectionTrainingSavePoint) -> None:
        super().__init__("yolov8 detection training paused")
        self.savepoint = savepoint


class YoloV8DetectionTrainingTerminatedError(Exception):
    """表示训练在 epoch 边界按请求终止。"""

    def __init__(self) -> None:
        super().__init__("yolov8 detection training terminated")


def run_yolov8_detection_training(
    request: YoloV8DetectionTrainingExecutionRequest,
) -> YoloV8DetectionTrainingExecutionResult:
    """执行一轮 YOLOv8 detection 训练。"""

    if request.model_type != "yolov8":
        raise InvalidRequestError(
            "YOLOv8 detection 训练入口只接受 model_type=yolov8，"
            "YOLO11 / YOLO26 必须使用各自 detection 训练入口",
            details={"model_type": request.model_type},
        )

    imports = _require_training_imports()
    manifest_payload = dict(request.manifest_payload)
    yolov8_data_context = prepare_yolov8_detection_training_data_context(
        dataset_storage=request.dataset_storage,
        cv2_module=imports.cv2,
        manifest_payload=manifest_payload,
    )
    resolved_splits = yolov8_data_context.resolved_splits
    train_split = yolov8_data_context.train_split
    validation_split = yolov8_data_context.validation_split
    train_samples = yolov8_data_context.train_samples
    category_names = yolov8_data_context.category_names
    category_ids = yolov8_data_context.category_ids
    validation_samples = yolov8_data_context.validation_samples
    input_size = _resolve_input_size(request.input_size)
    batch_size = max(1, int(request.batch_size or YOLOV8_DETECTION_DEFAULT_BATCH_SIZE))
    max_epochs = max(1, int(request.max_epochs or YOLOV8_DETECTION_DEFAULT_MAX_EPOCHS))
    evaluation_interval = max(
        1,
        int(request.evaluation_interval or YOLOV8_DETECTION_DEFAULT_EVALUATION_INTERVAL),
    )
    extra_options = dict(request.extra_options or {})
    device, gpu_count, device_ids, distributed_mode, runtime_precision = (
        _resolve_runtime(
            imports=imports,
            requested_gpu_count=request.gpu_count,
            requested_precision=request.precision,
        )
    )
    learning_rate = _read_float_option(extra_options, "learning_rate", default=0.01)
    weight_decay = _read_float_option(extra_options, "weight_decay", default=5e-4)
    class_loss_weight = _read_float_option(
        extra_options,
        "class_loss_weight",
        default=YOLOV8_DETECTION_DEFAULT_CLASS_LOSS_WEIGHT,
    )
    box_loss_weight = _read_float_option(
        extra_options,
        "box_loss_weight",
        default=YOLOV8_DETECTION_DEFAULT_BOX_LOSS_WEIGHT,
    )
    dfl_loss_weight = _read_float_option(
        extra_options,
        "dfl_loss_weight",
        default=YOLOV8_DETECTION_DEFAULT_DFL_LOSS_WEIGHT,
    )
    evaluation_confidence_threshold = _read_float_option(
        extra_options,
        "evaluation_confidence_threshold",
        default=YOLOV8_DETECTION_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
    )
    evaluation_nms_threshold = _read_float_option(
        extra_options,
        "evaluation_nms_threshold",
        default=YOLOV8_DETECTION_DEFAULT_EVAL_NMS_THRESHOLD,
    )
    assign_topk = max(
        1,
        _read_int_option(
            extra_options, "assign_topk", default=YOLOV8_DETECTION_DEFAULT_ASSIGN_TOPK
        ),
    )
    assign_alpha = _read_float_option(
        extra_options,
        "assign_alpha",
        default=YOLOV8_DETECTION_DEFAULT_ASSIGN_ALPHA,
    )
    assign_beta = _read_float_option(
        extra_options,
        "assign_beta",
        default=YOLOV8_DETECTION_DEFAULT_ASSIGN_BETA,
    )
    min_lr_ratio = _read_float_option(
        extra_options,
        "min_lr_ratio",
        default=YOLOV8_DETECTION_DEFAULT_MIN_LR_RATIO,
    )
    grad_clip_norm = _read_float_option(
        extra_options,
        "grad_clip_norm",
        default=YOLOV8_DETECTION_DEFAULT_GRAD_CLIP_NORM,
    )
    augmentation_options = _resolve_detection_augmentation_options(extra_options)
    validation_split_name = (
        validation_split.name if validation_split is not None else None
    )

    model = build_yolov8_model(
        task_type="detection",
        model_scale=request.model_scale,
        num_classes=len(category_names),
    )

    warm_start_summary = {
        "enabled": False,
        "source_model_version_id": None,
        "source_kind": None,
        "source_model_name": None,
        "source_model_scale": None,
        "load_summary": None,
    }
    if request.warm_start_checkpoint_path is not None:
        warm_start_summary = _load_warm_start_checkpoint(
            imports=imports,
            model=model,
            checkpoint_path=request.warm_start_checkpoint_path,
            source_summary=request.warm_start_source_summary or {},
        )

    parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
    training_runtime = build_yolov8_detection_training_runtime(
        torch_module=imports.torch,
        model=model,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        max_epochs=max_epochs,
        min_lr_ratio=min_lr_ratio,
        batch_size=batch_size,
        train_sample_count=len(train_samples),
        num_classes=len(category_names),
        device=device,
        runtime_precision=runtime_precision,
    )
    optimizer = training_runtime.optimizer
    scheduler = training_runtime.scheduler
    scaler = training_runtime.scaler
    training_schedule = training_runtime.schedule
    resume_state: _LoadedResumeState | None = None
    if request.resume_checkpoint_path is not None:
        resume_state = _load_resume_checkpoint(
            imports=imports,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            checkpoint_path=request.resume_checkpoint_path,
            expected_model_type=request.model_type,
            expected_model_scale=request.model_scale,
            expected_num_classes=len(category_names),
            expected_input_size=input_size,
            expected_batch_size=batch_size,
            expected_max_epochs=max_epochs,
            expected_precision=runtime_precision,
            expected_validation_split_name=validation_split_name,
            expected_evaluation_interval=evaluation_interval,
            expected_evaluation_confidence_threshold=(
                evaluation_confidence_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            expected_evaluation_nms_threshold=(
                evaluation_nms_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            expected_learning_rate=learning_rate,
            expected_weight_decay=weight_decay,
            expected_class_loss_weight=class_loss_weight,
            expected_box_loss_weight=box_loss_weight,
            expected_dfl_loss_weight=dfl_loss_weight,
            expected_assign_topk=assign_topk,
            expected_assign_alpha=assign_alpha,
            expected_assign_beta=assign_beta,
            expected_min_lr_ratio=min_lr_ratio,
            expected_grad_clip_norm=grad_clip_norm,
        )
        warm_start_summary = dict(resume_state.warm_start_summary)

    model.to(device)
    if runtime_precision == "fp16":
        model.half()
    if resume_state is not None:
        move_yolov8_optimizer_state_to_device(optimizer=optimizer, device=device)
    autocast_context = _build_autocast_context(
        imports=imports,
        device=device,
        runtime_precision=runtime_precision,
    )
    metrics_history: list[dict[str, object]] = (
        [dict(item) for item in resume_state.epoch_history]
        if resume_state is not None
        else []
    )
    validation_history: list[dict[str, object]] = (
        [dict(item) for item in resume_state.validation_history]
        if resume_state is not None
        else []
    )
    evaluated_epochs: list[int] = (
        list(resume_state.evaluated_epochs) if resume_state is not None else []
    )
    execution_plan = plan_yolov8_detection_training_execution(
        data_context=yolov8_data_context,
        batch_size=batch_size,
        max_epochs=max_epochs,
        resume_epoch=resume_state.resume_epoch if resume_state is not None else 0,
        resume_best_metric_name=(
            resume_state.best_metric_name if resume_state is not None else None
        ),
        resume_best_metric_value=(
            resume_state.best_metric_value if resume_state is not None else None
        ),
    )
    has_validation = execution_plan.has_validation
    best_metric_name = execution_plan.best_metric_name
    best_metric_value = execution_plan.best_metric_value
    total_iterations = execution_plan.total_iterations
    global_iteration = execution_plan.initial_global_iteration
    latest_checkpoint_bytes = b""
    best_checkpoint_bytes = (
        _build_checkpoint_bytes_from_state(
            imports=imports,
            checkpoint_state=resume_state.best_checkpoint_state,
        )
        if resume_state is not None and resume_state.best_checkpoint_state is not None
        else b""
    )
    resume_epoch = resume_state.resume_epoch if resume_state is not None else 0

    for epoch in range(resume_epoch + 1, max_epochs + 1):
        def on_yolov8_batch_progress(
            progress: YoloV8DetectionTrainingBatchProgress,
        ) -> None:
            """把 YOLOv8 core batch 进度透传给平台回调。"""

            if request.batch_callback is None:
                return
            request.batch_callback(progress)

        epoch_result = run_yolov8_detection_training_epoch(
            torch_module=imports.torch,
            model=model,
            samples=train_samples,
            batch_size=batch_size,
            input_size=input_size,
            epoch=epoch,
            max_epochs=max_epochs,
            global_iteration=global_iteration,
            total_iterations=total_iterations,
            optimizer=optimizer,
            scaler=scaler,
            training_schedule=training_schedule,
            autocast_context=autocast_context,
            build_batch=lambda sample_batch, available_samples, current_epoch: (
                _build_training_batch_for_epoch(
                    imports=imports,
                    samples=sample_batch,
                    available_samples=available_samples,
                    base_input_size=input_size,
                    epoch=current_epoch,
                    max_epochs=max_epochs,
                    device=device,
                    runtime_precision=runtime_precision,
                    augmentation_options=augmentation_options,
                )
            ),
            unwrap_outputs=_unwrap_detection_outputs,
            compute_loss=lambda **kwargs: _compute_detection_loss(
                imports=imports,
                num_classes=len(category_names),
                class_loss_weight=class_loss_weight,
                box_loss_weight=box_loss_weight,
                dfl_loss_weight=dfl_loss_weight,
                assign_topk=assign_topk,
                assign_alpha=assign_alpha,
                assign_beta=assign_beta,
                **kwargs,
            ),
            grad_clip_norm=grad_clip_norm,
            batch_callback=(
                on_yolov8_batch_progress if request.batch_callback is not None else None
            ),
        )
        global_iteration = epoch_result.global_iteration
        train_metrics = dict(epoch_result.train_metrics)
        train_metrics["epoch"] = epoch
        metrics_history.append(train_metrics)

        validation_ran = should_run_yolov8_detection_validation(
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            validation_sample_count=len(validation_samples),
        )
        validation_snapshot: dict[str, object] | None = None
        validation_metrics: dict[str, float] = {}
        current_metric_value: float | None = None
        if validation_ran:
            validation_snapshot = _evaluate_detection_model(
                imports=imports,
                model=model,
                samples=validation_samples,
                category_ids=category_ids,
                annotation_file=validation_split.annotation_file
                if validation_split is not None
                else None,
                annotation_payload=validation_split.annotation_payload
                if validation_split is not None
                else None,
                input_size=input_size,
                batch_size=batch_size,
                device=device,
                runtime_precision=runtime_precision,
                num_classes=len(category_names),
                class_loss_weight=class_loss_weight,
                box_loss_weight=box_loss_weight,
                dfl_loss_weight=dfl_loss_weight,
                assign_topk=assign_topk,
                assign_alpha=assign_alpha,
                assign_beta=assign_beta,
                confidence_threshold=evaluation_confidence_threshold,
                nms_threshold=evaluation_nms_threshold,
            )
            validation_history.append(validation_snapshot)
            validation_metrics = {
                "loss": float(validation_snapshot["loss"]),
                "map50": float(validation_snapshot["map50"]),
                "map50_95": float(validation_snapshot["map50_95"]),
            }
            evaluated_epochs.append(epoch)
            current_metric_value = validation_metrics[best_metric_name]

        best_metric_update = resolve_yolov8_detection_best_metric_update(
            validation_ran=validation_ran,
            current_metric_value=current_metric_value,
            train_loss=float(train_metrics["loss"]),
            best_metric_value=best_metric_value,
        )
        improved_best = best_metric_update.improved
        candidate_best_metric_value = best_metric_update.candidate_value

        scheduler.step()
        checkpoint_update = build_yolov8_detection_epoch_checkpoint_update(
            torch_module=imports.torch,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            model_type=request.model_type,
            model_scale=request.model_scale,
            category_names=category_names,
            input_size=input_size,
            batch_size=batch_size,
            max_epochs=max_epochs,
            epoch=epoch,
            precision=runtime_precision,
            validation_split_name=validation_split_name,
            evaluation_interval=evaluation_interval,
            evaluation_confidence_threshold=(
                evaluation_confidence_threshold if has_validation else None
            ),
            evaluation_nms_threshold=(
                evaluation_nms_threshold if has_validation else None
            ),
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            class_loss_weight=class_loss_weight,
            box_loss_weight=box_loss_weight,
            dfl_loss_weight=dfl_loss_weight,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            min_lr_ratio=min_lr_ratio,
            grad_clip_norm=grad_clip_norm,
            metrics_history=metrics_history,
            validation_history=validation_history,
            evaluated_epochs=tuple(evaluated_epochs),
            warm_start_summary=warm_start_summary,
            implementation_mode=request.implementation_mode,
            augmentation_options=_serialize_detection_augmentation_options(
                augmentation_options
            ),
            best_metric_name=best_metric_name,
            candidate_best_metric_value=candidate_best_metric_value,
            previous_best_checkpoint_bytes=best_checkpoint_bytes,
            improved_best=improved_best,
        )
        latest_checkpoint_bytes = checkpoint_update.latest_checkpoint_bytes
        best_checkpoint_bytes = checkpoint_update.best_checkpoint_bytes
        best_metric_value = checkpoint_update.best_metric_value

        control_command = None
        if request.epoch_callback is not None:
            control_command = request.epoch_callback(
                YoloV8DetectionTrainingEpochProgress(
                    epoch=epoch,
                    max_epochs=max_epochs,
                    evaluation_interval=evaluation_interval,
                    validation_ran=validation_ran,
                    evaluated_epochs=tuple(evaluated_epochs),
                    train_metrics=train_metrics,
                    validation_metrics=validation_metrics,
                    train_metrics_snapshot={
                        "history": metrics_history,
                        "final_metrics": train_metrics,
                    },
                    validation_snapshot=validation_snapshot,
                    current_metric_name=best_metric_name,
                    current_metric_value=current_metric_value,
                    best_metric_name=best_metric_name,
                    best_metric_value=serialize_yolov8_detection_best_metric_value(
                        has_validation=has_validation,
                        best_metric_value=best_metric_value,
                    ),
                )
            )
        control_decision = resolve_yolov8_detection_epoch_control(
            save_checkpoint_requested=(
                control_command.save_checkpoint if control_command is not None else False
            ),
            pause_training_requested=(
                control_command.pause_training if control_command is not None else False
            ),
            terminate_training_requested=(
                control_command.terminate_training
                if control_command is not None
                else False
            )
        )
        should_write_savepoint = control_decision.save_checkpoint
        should_pause_training = control_decision.pause_training
        should_terminate_training = control_decision.terminate_training
        if should_write_savepoint:
            savepoint_payload = build_yolov8_detection_training_savepoint_payload(
                epoch=epoch,
                latest_checkpoint_bytes=latest_checkpoint_bytes,
                best_checkpoint_bytes=best_checkpoint_bytes,
                best_metric_name=best_metric_name,
                best_metric_value=best_metric_value,
                has_validation=has_validation,
            )
            savepoint = YoloV8DetectionTrainingSavePoint(
                epoch=savepoint_payload.epoch,
                latest_checkpoint_bytes=savepoint_payload.latest_checkpoint_bytes,
                best_checkpoint_bytes=savepoint_payload.best_checkpoint_bytes,
                best_metric_name=savepoint_payload.best_metric_name,
                best_metric_value=savepoint_payload.best_metric_value,
            )
            if request.savepoint_callback is not None:
                request.savepoint_callback(savepoint)
            if should_pause_training:
                raise YoloV8DetectionTrainingPausedError(savepoint)
        if should_terminate_training:
            raise YoloV8DetectionTrainingTerminatedError()

    if not best_checkpoint_bytes:
        best_checkpoint_bytes = latest_checkpoint_bytes
    if validation_split is not None and best_metric_value == float("-inf"):
        best_metric_value = 0.0
    if validation_split is None and best_metric_value == float("inf"):
        best_metric_value = 0.0

    evaluation_postprocess_mode = DETECTION_POSTPROCESS_MODE_NMS
    evaluation_max_detections = None

    validation_metrics_payload = {
        "enabled": validation_split is not None and bool(validation_samples),
        "evaluation_interval": evaluation_interval,
        "split_name": validation_split.name if validation_split is not None else None,
        "sample_count": len(validation_samples),
        "confidence_threshold": (
            evaluation_confidence_threshold
            if validation_split is not None and bool(validation_samples)
            else None
        ),
        "nms_threshold": (
            evaluation_nms_threshold
            if validation_split is not None
            and bool(validation_samples)
            and evaluation_postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS
            else None
        ),
        "postprocess_mode": (
            evaluation_postprocess_mode
            if validation_split is not None and bool(validation_samples)
            else None
        ),
        "max_detections": (
            evaluation_max_detections
            if validation_split is not None and bool(validation_samples)
            else None
        ),
        "best_metric_name": best_metric_name
        if validation_split is not None and bool(validation_samples)
        else None,
        "best_metric_value": (
            round(best_metric_value, 6)
            if validation_split is not None and bool(validation_samples)
            else None
        ),
        "evaluated_epochs": evaluated_epochs,
        "epoch_history": validation_history,
        "final_metrics": validation_history[-1] if validation_history else {},
    }
    metrics_payload = {
        "implementation_mode": request.implementation_mode,
        "device": device,
        "gpu_count": gpu_count,
        "device_ids": list(device_ids),
        "distributed_mode": distributed_mode,
        "precision": runtime_precision,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "evaluation_interval": evaluation_interval,
        "input_size": list(input_size),
        "train_split_name": train_split.name,
        "validation_split_name": validation_split.name
        if validation_split is not None
        else None,
        "sample_count": sum(split.sample_count for split in resolved_splits),
        "train_sample_count": len(train_samples),
        "validation_sample_count": len(validation_samples),
        "category_names": list(category_names),
        "best_metric_name": best_metric_name,
        "best_metric_value": round(best_metric_value, 6),
        "epoch_history": metrics_history,
        "final_metrics": metrics_history[-1] if metrics_history else {},
        "parameter_count": parameter_count,
        "warm_start": warm_start_summary,
        "optimizer": {
            "name": training_runtime.schedule.optimizer_name,
            "learning_rate": training_runtime.schedule.initial_lr,
            "weight_decay": training_runtime.schedule.weight_decay,
            "scaled_weight_decay": training_runtime.schedule.scaled_weight_decay,
            "nominal_batch_size": training_runtime.schedule.nominal_batch_size,
            "accumulate": training_runtime.schedule.accumulate,
        },
        "scheduler": {
            "name": "UltralyticsCosineLambdaLR",
            "min_lr_ratio": min_lr_ratio,
            "warmup_iterations": training_runtime.schedule.warmup_iterations,
            "warmup_momentum": training_runtime.schedule.warmup_momentum,
            "warmup_bias_lr": training_runtime.schedule.warmup_bias_lr,
            "latest_learning_rate": float(optimizer.param_groups[0]["lr"]),
        },
        "evaluation": {
            "split_name": validation_split_name,
            "confidence_threshold": (
                evaluation_confidence_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            "nms_threshold": (
                evaluation_nms_threshold
                if validation_split is not None
                and bool(validation_samples)
                and evaluation_postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS
                else None
            ),
            "postprocess_mode": evaluation_postprocess_mode,
            "max_detections": evaluation_max_detections,
        },
        "loss_weights": {
            "class_loss_weight": class_loss_weight,
            "box_loss_weight": box_loss_weight,
            "dfl_loss_weight": dfl_loss_weight,
        },
        "assignment": {
            "assign_topk": assign_topk,
            "assign_alpha": assign_alpha,
            "assign_beta": assign_beta,
        },
        "gradient_control": {
            "grad_clip_norm": grad_clip_norm,
        },
        "augmentation": _serialize_detection_augmentation_options(augmentation_options),
    }
    return YoloV8DetectionTrainingExecutionResult(
        checkpoint_bytes=best_checkpoint_bytes,
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload=metrics_payload,
        validation_metrics_payload=validation_metrics_payload,
        warm_start_summary=warm_start_summary,
        implementation_mode=request.implementation_mode,
        best_metric_name=best_metric_name,
        best_metric_value=round(best_metric_value, 6),
        evaluation_interval=evaluation_interval,
        category_names=category_names,
        split_names=tuple(split.name for split in resolved_splits),
        sample_count=sum(split.sample_count for split in resolved_splits),
        train_sample_count=len(train_samples),
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        device=device,
        gpu_count=gpu_count,
        device_ids=device_ids,
        distributed_mode=distributed_mode,
        precision=runtime_precision,
        validation_split_name=validation_split.name
        if validation_split is not None
        else None,
        validation_sample_count=len(validation_samples),
        parameter_count=parameter_count,
    )


def _require_training_imports() -> _TrainingImports:
    """导入 YOLO 主线 detection 训练所需依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except Exception as error:  # pragma: no cover - 缺依赖时直接报配置错误
        raise ServiceConfigurationError(
            "当前环境缺少 YOLO 主线 detection 训练所需依赖",
            details={"error": str(error)},
        ) from error
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except Exception:
        COCO = None
        COCOeval = None
    return _TrainingImports(cv2=cv2, np=np, torch=torch, COCO=COCO, COCOeval=COCOeval)


def _resolve_input_size(input_size: tuple[int, int] | None) -> tuple[int, int]:
    """解析训练输入尺寸。"""

    if input_size is None:
        return YOLOV8_DETECTION_DEFAULT_INPUT_SIZE
    return tuple(int(item) for item in input_size)


def _resolve_runtime(
    *,
    imports: _TrainingImports,
    requested_gpu_count: int | None,
    requested_precision: str | None,
) -> tuple[str, int, tuple[int, ...], str, str]:
    """解析当前训练真正使用的运行时资源。"""

    del requested_gpu_count
    torch = imports.torch
    cuda_available = bool(torch.cuda.is_available())
    if cuda_available:
        runtime_precision = "fp16" if requested_precision == "fp16" else "fp32"
        return "cuda:0", 1, (0,), "single-process", runtime_precision
    return "cpu", 0, (), "single-process", "fp32"


def _load_warm_start_checkpoint(
    *,
    imports: _TrainingImports,
    model: Any,
    checkpoint_path: Path,
    source_summary: dict[str, object],
) -> dict[str, object]:
    """加载 warm start checkpoint 并返回摘要。"""

    load_summary = load_yolo_checkpoint(
        imports=imports,
        model=model,
        checkpoint_path=checkpoint_path,
    )
    return {
        "enabled": True,
        "source_model_version_id": source_summary.get("source_model_version_id"),
        "source_kind": source_summary.get("source_kind"),
        "source_model_name": source_summary.get("source_model_name"),
        "source_model_scale": source_summary.get("source_model_scale"),
        "load_summary": load_summary,
    }


def _load_resume_checkpoint(
    *,
    imports: _TrainingImports,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    checkpoint_path: Path,
    expected_model_type: str,
    expected_model_scale: str,
    expected_num_classes: int,
    expected_input_size: tuple[int, int],
    expected_batch_size: int,
    expected_max_epochs: int,
    expected_precision: str,
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
    expected_learning_rate: float,
    expected_weight_decay: float,
    expected_class_loss_weight: float,
    expected_box_loss_weight: float,
    expected_dfl_loss_weight: float,
    expected_assign_topk: int,
    expected_assign_alpha: float,
    expected_assign_beta: float,
    expected_min_lr_ratio: float,
    expected_grad_clip_norm: float,
) -> _LoadedResumeState:
    """从 latest checkpoint 恢复训练状态。"""

    checkpoint_payload = imports.torch.load(checkpoint_path, map_location="cpu")
    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError("resume checkpoint 内容不合法")
    _validate_resume_checkpoint(
        checkpoint_payload=checkpoint_payload,
        expected_model_type=expected_model_type,
        expected_model_scale=expected_model_scale,
        expected_num_classes=expected_num_classes,
        expected_input_size=expected_input_size,
        expected_batch_size=expected_batch_size,
        expected_max_epochs=expected_max_epochs,
        expected_precision=expected_precision,
        expected_validation_split_name=expected_validation_split_name,
        expected_evaluation_interval=expected_evaluation_interval,
        expected_evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
        expected_evaluation_nms_threshold=expected_evaluation_nms_threshold,
        expected_learning_rate=expected_learning_rate,
        expected_weight_decay=expected_weight_decay,
        expected_class_loss_weight=expected_class_loss_weight,
        expected_box_loss_weight=expected_box_loss_weight,
        expected_dfl_loss_weight=expected_dfl_loss_weight,
        expected_assign_topk=expected_assign_topk,
        expected_assign_alpha=expected_assign_alpha,
        expected_assign_beta=expected_assign_beta,
        expected_min_lr_ratio=expected_min_lr_ratio,
        expected_grad_clip_norm=expected_grad_clip_norm,
    )
    model.load_state_dict(dict(checkpoint_payload.get("model_state_dict") or {}))
    optimizer_state_dict = checkpoint_payload.get("optimizer_state_dict")
    if isinstance(optimizer_state_dict, dict):
        optimizer.load_state_dict(optimizer_state_dict)
    scheduler_state_dict = checkpoint_payload.get("scheduler_state_dict")
    if not isinstance(scheduler_state_dict, dict):
        raise InvalidRequestError("resume checkpoint 缺少 scheduler_state_dict")
    scheduler.load_state_dict(scheduler_state_dict)
    scaler_state_dict = checkpoint_payload.get("scaler_state_dict")
    if not isinstance(scaler_state_dict, dict):
        raise InvalidRequestError("resume checkpoint 缺少 scaler_state_dict")
    scaler.load_state_dict(scaler_state_dict)

    raw_resume_epoch = checkpoint_payload.get("epoch")
    resume_epoch = (
        int(raw_resume_epoch)
        if isinstance(raw_resume_epoch, int) and raw_resume_epoch >= 0
        else 0
    )
    raw_best_metric_name = checkpoint_payload.get("best_metric_name")
    best_metric_name = (
        str(raw_best_metric_name)
        if isinstance(raw_best_metric_name, str) and raw_best_metric_name.strip()
        else "map50_95"
    )
    raw_best_metric_value = checkpoint_payload.get("best_metric_value")
    best_metric_value = (
        float(raw_best_metric_value)
        if isinstance(raw_best_metric_value, int | float)
        else None
    )
    warm_start_summary = checkpoint_payload.get("warm_start")
    return _LoadedResumeState(
        resume_epoch=resume_epoch,
        epoch_history=_normalize_history_items(
            checkpoint_payload.get("metrics_history")
        ),
        validation_history=_normalize_history_items(
            checkpoint_payload.get("validation_history")
        ),
        evaluated_epochs=_normalize_evaluated_epochs(
            checkpoint_payload.get("evaluated_epochs")
        ),
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=(
            dict(checkpoint_payload.get("best_checkpoint_state"))
            if isinstance(checkpoint_payload.get("best_checkpoint_state"), dict)
            else None
        ),
        warm_start_summary=(
            dict(warm_start_summary)
            if isinstance(warm_start_summary, dict)
            else {
                "enabled": False,
                "source_model_version_id": None,
                "source_kind": None,
                "source_model_name": None,
                "source_model_scale": None,
                "load_summary": None,
            }
        ),
    )


def _validate_resume_checkpoint(
    *,
    checkpoint_payload: dict[str, object],
    expected_model_type: str,
    expected_model_scale: str,
    expected_num_classes: int,
    expected_input_size: tuple[int, int],
    expected_batch_size: int,
    expected_max_epochs: int,
    expected_precision: str,
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
    expected_learning_rate: float,
    expected_weight_decay: float,
    expected_class_loss_weight: float,
    expected_box_loss_weight: float,
    expected_dfl_loss_weight: float,
    expected_assign_topk: int,
    expected_assign_alpha: float,
    expected_assign_beta: float,
    expected_min_lr_ratio: float,
    expected_grad_clip_norm: float,
) -> None:
    """校验恢复训练使用的 checkpoint 是否与当前请求匹配。"""

    if expected_model_type == "yolov8":
        validate_yolov8_detection_resume_checkpoint(
            checkpoint_payload=checkpoint_payload,
            request=YoloV8DetectionResumeValidationRequest(
                model_type=expected_model_type,
                model_scale=expected_model_scale,
                num_classes=expected_num_classes,
                input_size=expected_input_size,
                batch_size=expected_batch_size,
                max_epochs=expected_max_epochs,
                precision=expected_precision,
                validation_split_name=expected_validation_split_name,
                evaluation_interval=expected_evaluation_interval,
                evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
                evaluation_nms_threshold=expected_evaluation_nms_threshold,
                learning_rate=expected_learning_rate,
                weight_decay=expected_weight_decay,
                class_loss_weight=expected_class_loss_weight,
                box_loss_weight=expected_box_loss_weight,
                dfl_loss_weight=expected_dfl_loss_weight,
                assign_topk=expected_assign_topk,
                assign_alpha=expected_assign_alpha,
                assign_beta=expected_assign_beta,
                min_lr_ratio=expected_min_lr_ratio,
                grad_clip_norm=expected_grad_clip_norm,
            ),
        )
        return
    checkpoint_model_type = checkpoint_payload.get("model_type")
    checkpoint_model_scale = checkpoint_payload.get("model_scale")
    checkpoint_category_names = checkpoint_payload.get("category_names")
    checkpoint_input_size = checkpoint_payload.get("input_size")
    checkpoint_batch_size = checkpoint_payload.get("batch_size")
    checkpoint_max_epochs = checkpoint_payload.get("max_epochs")
    checkpoint_precision = checkpoint_payload.get("precision")
    if checkpoint_model_type != expected_model_type:
        raise InvalidRequestError(
            "resume checkpoint 的 model_type 与当前训练请求不一致",
            details={
                "checkpoint_model_type": checkpoint_model_type,
                "expected_model_type": expected_model_type,
            },
        )
    if checkpoint_model_scale != expected_model_scale:
        raise InvalidRequestError(
            "resume checkpoint 的 model_scale 与当前训练请求不一致",
            details={
                "checkpoint_model_scale": checkpoint_model_scale,
                "expected_model_scale": expected_model_scale,
            },
        )
    if (
        not isinstance(checkpoint_category_names, list)
        or len(checkpoint_category_names) != expected_num_classes
    ):
        raise InvalidRequestError(
            "resume checkpoint 的类别数量与当前训练请求不一致",
            details={
                "checkpoint_class_count": (
                    len(checkpoint_category_names)
                    if isinstance(checkpoint_category_names, list)
                    else None
                ),
                "expected_class_count": expected_num_classes,
            },
        )
    if (
        not isinstance(checkpoint_input_size, list)
        or len(checkpoint_input_size) != 2
        or tuple(int(item) for item in checkpoint_input_size) != expected_input_size
    ):
        raise InvalidRequestError(
            "resume checkpoint 的 input_size 与当前训练请求不一致",
            details={
                "checkpoint_input_size": checkpoint_input_size,
                "expected_input_size": list(expected_input_size),
            },
        )
    if checkpoint_batch_size != expected_batch_size:
        raise InvalidRequestError(
            "resume checkpoint 的 batch_size 与当前训练请求不一致",
            details={
                "checkpoint_batch_size": checkpoint_batch_size,
                "expected_batch_size": expected_batch_size,
            },
        )
    if checkpoint_max_epochs != expected_max_epochs:
        raise InvalidRequestError(
            "resume checkpoint 的 max_epochs 与当前训练请求不一致",
            details={
                "checkpoint_max_epochs": checkpoint_max_epochs,
                "expected_max_epochs": expected_max_epochs,
            },
        )
    if checkpoint_precision != expected_precision:
        raise InvalidRequestError(
            "resume checkpoint 的 precision 与当前训练请求不一致",
            details={
                "checkpoint_precision": checkpoint_precision,
                "expected_precision": expected_precision,
            },
        )
    _validate_resume_validation_configuration(
        checkpoint_payload=checkpoint_payload,
        expected_validation_split_name=expected_validation_split_name,
        expected_evaluation_interval=expected_evaluation_interval,
        expected_evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
        expected_evaluation_nms_threshold=expected_evaluation_nms_threshold,
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("learning_rate"),
        expected_value=expected_learning_rate,
        field_name="learning_rate",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("weight_decay"),
        expected_value=expected_weight_decay,
        field_name="weight_decay",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("class_loss_weight"),
        expected_value=expected_class_loss_weight,
        field_name="class_loss_weight",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("box_loss_weight"),
        expected_value=expected_box_loss_weight,
        field_name="box_loss_weight",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("dfl_loss_weight"),
        expected_value=expected_dfl_loss_weight,
        field_name="dfl_loss_weight",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_alpha"),
        expected_value=expected_assign_alpha,
        field_name="assign_alpha",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_beta"),
        expected_value=expected_assign_beta,
        field_name="assign_beta",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("min_lr_ratio"),
        expected_value=expected_min_lr_ratio,
        field_name="min_lr_ratio",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("grad_clip_norm"),
        expected_value=expected_grad_clip_norm,
        field_name="grad_clip_norm",
    )
    _assert_resume_required_int_matches(
        checkpoint_value=checkpoint_payload.get("assign_topk"),
        expected_value=expected_assign_topk,
        field_name="assign_topk",
    )


def _validate_resume_validation_configuration(
    *,
    checkpoint_payload: dict[str, object],
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
) -> None:
    """校验 resume checkpoint 中记录的验证配置是否与当前任务一致。"""

    checkpoint_validation_split_name = checkpoint_payload.get("validation_split_name")
    if checkpoint_validation_split_name != expected_validation_split_name:
        raise InvalidRequestError(
            "resume checkpoint 的 validation_split_name 与当前训练请求不一致",
            details={
                "checkpoint_validation_split_name": checkpoint_validation_split_name,
                "expected_validation_split_name": expected_validation_split_name,
            },
        )
    if expected_validation_split_name is None:
        return
    checkpoint_evaluation_interval = checkpoint_payload.get("evaluation_interval")
    if checkpoint_evaluation_interval != expected_evaluation_interval:
        raise InvalidRequestError(
            "resume checkpoint 的 evaluation_interval 与当前训练请求不一致",
            details={
                "checkpoint_evaluation_interval": checkpoint_evaluation_interval,
                "expected_evaluation_interval": expected_evaluation_interval,
            },
        )
    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_confidence_threshold"),
        expected_value=expected_evaluation_confidence_threshold,
        field_name="evaluation_confidence_threshold",
    )
    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_nms_threshold"),
        expected_value=expected_evaluation_nms_threshold,
        field_name="evaluation_nms_threshold",
    )


def _assert_resume_required_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的必填浮点配置与当前任务一致。"""

    if not isinstance(checkpoint_value, int | float) or not math.isclose(
        float(checkpoint_value),
        float(expected_value),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise InvalidRequestError(
            f"resume checkpoint 的 {field_name} 与当前训练请求不一致"
        )


def _assert_resume_optional_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float | None,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的可选浮点配置与当前任务一致。"""

    if expected_value is None:
        if checkpoint_value is not None:
            raise InvalidRequestError(
                f"resume checkpoint 的 {field_name} 与当前训练请求不一致"
            )
        return
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_value,
        expected_value=expected_value,
        field_name=field_name,
    )


def _assert_resume_required_int_matches(
    *,
    checkpoint_value: object,
    expected_value: int,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的必填整型配置与当前任务一致。"""

    if not isinstance(checkpoint_value, int) or int(checkpoint_value) != int(
        expected_value
    ):
        raise InvalidRequestError(
            f"resume checkpoint 的 {field_name} 与当前训练请求不一致"
        )


def _build_autocast_context(
    *,
    imports: _TrainingImports,
    device: str,
    runtime_precision: str,
) -> Callable[[], Any]:
    """构造训练阶段使用的 autocast 上下文工厂。"""

    torch = imports.torch
    use_fp16 = device.startswith("cuda") and runtime_precision == "fp16"
    autocast = getattr(torch, "autocast", None)
    if use_fp16 and callable(autocast):
        return lambda: autocast(device_type="cuda", dtype=torch.float16)
    return nullcontext


def _iter_batches(
    samples: list[_ResolvedTrainingSample],
    batch_size: int,
):
    """按 batch size 迭代样本。"""

    for batch_start in range(0, len(samples), batch_size):
        yield samples[batch_start : batch_start + batch_size]


def _unwrap_detection_outputs(outputs: Any) -> dict[str, Any]:
    """把 detection 训练输出规整成 one2many 结果。"""

    if isinstance(outputs, dict) and "boxes" in outputs and "scores" in outputs:
        return outputs
    if isinstance(outputs, dict) and "one2many" in outputs:
        one2many = outputs.get("one2many")
        if isinstance(one2many, dict) and "boxes" in one2many and "scores" in one2many:
            return one2many
    raise ServiceConfigurationError("当前 YOLO detection 训练输出结构不合法")


def _compute_detection_loss(
    *,
    imports: _TrainingImports,
    model: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[_PreparedTrainingTarget, ...],
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """按 YOLOv8 core 规则计算 detection 训练损失。"""

    torch = imports.torch
    if not is_yolov8_detection_core_model(model):
        raise ServiceConfigurationError(
            "YOLOv8 detection 训练损失只接受 YOLOv8 core 模型"
        )
    return compute_yolov8_detection_training_loss(
        torch_module=torch,
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=batch_targets,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
        assign_topk2=assign_topk2,
    )


def _evaluate_detection_model(
    *,
    imports: _TrainingImports,
    model: Any,
    samples: tuple[_ResolvedTrainingSample, ...],
    category_ids: tuple[int, ...],
    annotation_file: Path | None,
    annotation_payload: dict[str, object] | None,
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    confidence_threshold: float,
    nms_threshold: float,
) -> dict[str, object]:
    """在验证 split 上执行真实 detection loss 与 COCO mAP 评估。"""

    validation_losses = _evaluate_detection_validation_losses(
        imports=imports,
        model=model,
        samples=samples,
        input_size=input_size,
        batch_size=batch_size,
        device=device,
        runtime_precision=runtime_precision,
        num_classes=num_classes,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
    )
    validation_map = _evaluate_validation_map(
        imports=imports,
        model=model,
        samples=samples,
        input_size=input_size,
        batch_size=batch_size,
        device=device,
        runtime_precision=runtime_precision,
        category_ids=category_ids,
        annotation_file=annotation_file,
        annotation_payload=annotation_payload,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
    )
    evaluation_summary = {
        "loss": round(float(validation_losses.get("loss", 0.0)), 6),
        "class_loss": round(float(validation_losses.get("class_loss", 0.0)), 6),
        "box_loss": round(float(validation_losses.get("box_loss", 0.0)), 6),
        "dfl_loss": round(float(validation_losses.get("dfl_loss", 0.0)), 6),
        "map50": round(float(validation_map.get("map50", 0.0)), 6),
        "map50_95": round(float(validation_map.get("map50_95", 0.0)), 6),
        "sample_count": len(samples),
    }
    if "one2many_loss" in validation_losses:
        evaluation_summary["one2many_loss"] = round(
            float(validation_losses.get("one2many_loss", 0.0)),
            6,
        )
    if "one2one_loss" in validation_losses:
        evaluation_summary["one2one_loss"] = round(
            float(validation_losses.get("one2one_loss", 0.0)),
            6,
        )
    return evaluation_summary


def _evaluate_detection_validation_losses(
    *,
    imports: _TrainingImports,
    model: Any,
    samples: tuple[_ResolvedTrainingSample, ...],
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
) -> dict[str, float]:
    """在验证集上统计真实 detection 验证损失。"""

    if not samples:
        return {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}

    torch = imports.torch
    autocast_context = _build_autocast_context(
        imports=imports,
        device=device,
        runtime_precision=runtime_precision,
    )
    if not is_yolov8_detection_core_model(model):
        raise ServiceConfigurationError(
            "YOLOv8 detection 训练验证只接受 YOLOv8 core 模型"
        )
    return evaluate_yolov8_detection_validation_losses(
        torch_module=torch,
        model=model,
        samples=samples,
        batch_size=batch_size,
        build_batch=lambda batch_samples: build_yolov8_detection_training_batch(
            imports=imports,
            samples=batch_samples,
            input_size=input_size,
            device=device,
            runtime_precision=runtime_precision,
            augment_training=False,
        ),
        unwrap_outputs=_unwrap_detection_outputs,
        compute_loss=lambda **kwargs: _compute_detection_loss(
            imports=imports,
            num_classes=num_classes,
            **kwargs,
        ),
        autocast_context=autocast_context,
        freeze_batch_norm=lambda: _freeze_batch_norm_modules(
            imports=imports,
            model=model,
        ),
        restore_batch_norm=_restore_batch_norm_modules,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
    )


def _evaluate_validation_map(
    *,
    imports: _TrainingImports,
    model: Any,
    samples: tuple[_ResolvedTrainingSample, ...],
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    category_ids: tuple[int, ...],
    annotation_file: Path | None,
    annotation_payload: dict[str, object] | None,
    confidence_threshold: float,
    nms_threshold: float,
) -> dict[str, float]:
    """执行一次真实 COCO mAP 评估。"""

    if not samples or annotation_payload is None:
        return {"map50": 0.0, "map50_95": 0.0}
    if imports.COCO is None or imports.COCOeval is None:
        raise ServiceConfigurationError(
            "当前环境缺少 pycocotools，无法执行 detection mAP 验证"
        )

    torch = imports.torch
    previous_training_mode = bool(model.training)
    model.eval()
    detections: list[dict[str, object]] = []
    evaluation_postprocess_mode = DETECTION_POSTPROCESS_MODE_NMS
    try:
        with torch.no_grad():
            for batch_samples in _iter_batches(list(samples), batch_size):
                images, batch_targets = build_yolov8_detection_training_batch(
                    imports=imports,
                    samples=batch_samples,
                    input_size=input_size,
                    device=device,
                    runtime_precision=runtime_precision,
                    augment_training=False,
                )
                prediction_tensor = model(images)
                detections.extend(
                    _convert_yolov8_predictions_to_coco_detections(
                        imports=imports,
                        prediction_tensor=prediction_tensor,
                        batch_targets=batch_targets,
                        input_size=input_size,
                        category_ids=category_ids,
                        confidence_threshold=confidence_threshold,
                        nms_threshold=nms_threshold,
                        postprocess_mode=evaluation_postprocess_mode,
                        max_detections=None,
                    )
                )
    finally:
        model.train(previous_training_mode)

    if not detections:
        return {"map50": 0.0, "map50_95": 0.0}

    ground_truth = _load_coco_ground_truth_silently(
        imports=imports,
        annotation_file=annotation_file,
        annotation_payload=annotation_payload,
    )
    with redirect_stdout(io.StringIO()):
        coco_detections = ground_truth.loadRes(detections)
        coco_evaluator = imports.COCOeval(ground_truth, coco_detections, "bbox")
        coco_evaluator.evaluate()
        coco_evaluator.accumulate()
        coco_evaluator.summarize()
    return {
        "map50_95": float(coco_evaluator.stats[0]),
        "map50": float(coco_evaluator.stats[1]),
    }


def _convert_yolov8_predictions_to_coco_detections(
    *,
    imports: _TrainingImports,
    prediction_tensor: Any,
    batch_targets: tuple[_PreparedTrainingTarget, ...],
    input_size: tuple[int, int],
    category_ids: tuple[int, ...],
    confidence_threshold: float,
    nms_threshold: float,
    postprocess_mode: str = DETECTION_POSTPROCESS_MODE_NMS,
    max_detections: int | None = None,
) -> list[dict[str, object]]:
    """把主线 detection 预测结果转换为 COCO detection 列表。"""

    np_module = imports.np
    prediction_array = prediction_tensor.detach().cpu().numpy()
    postprocess_results = postprocess_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(category_ids),
        score_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        postprocess_mode=postprocess_mode,
        box_format="xywh",
        max_detections=max_detections,
    )
    detections: list[dict[str, object]] = []
    for batch_index, result in enumerate(postprocess_results):
        if result is None:
            continue
        target = batch_targets[batch_index]
        scale_x = float(input_size[1]) / max(1.0, float(target.image_width))
        scale_y = float(input_size[0]) / max(1.0, float(target.image_height))
        for bbox, score, class_id in zip(
            result.boxes_xyxy,
            result.scores,
            result.class_ids,
            strict=True,
        ):
            x1 = max(0.0, min(float(bbox[0]) / scale_x, float(target.image_width)))
            y1 = max(0.0, min(float(bbox[1]) / scale_y, float(target.image_height)))
            x2 = max(0.0, min(float(bbox[2]) / scale_x, float(target.image_width)))
            y2 = max(0.0, min(float(bbox[3]) / scale_y, float(target.image_height)))
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            resolved_class_id = int(class_id)
            if (
                width <= 0
                or height <= 0
                or resolved_class_id < 0
                or resolved_class_id >= len(category_ids)
            ):
                continue
            detections.append(
                {
                    "image_id": target.image_id,
                    "category_id": category_ids[resolved_class_id],
                    "bbox": [x1, y1, width, height],
                    "score": float(score),
                }
            )
    return detections


def _load_coco_ground_truth_silently(
    *,
    imports: _TrainingImports,
    annotation_file: Path | None,
    annotation_payload: dict[str, object] | None,
) -> Any:
    """静默加载 COCO ground truth。"""

    if imports.COCO is None:
        raise ServiceConfigurationError("当前环境缺少 pycocotools.COCO")
    with redirect_stdout(io.StringIO()):
        if annotation_file is not None:
            return imports.COCO(str(annotation_file))
        if annotation_payload is None:
            raise InvalidRequestError("缺少可用的 COCO ground truth 数据")
        ground_truth = imports.COCO()
        ground_truth.dataset = annotation_payload
        ground_truth.createIndex()
        return ground_truth


def _freeze_batch_norm_modules(
    *,
    imports: _TrainingImports,
    model: Any,
) -> tuple[tuple[Any, bool], ...]:
    """在验证阶段冻结 BatchNorm 的统计更新。"""

    batch_norm_states: list[tuple[Any, bool]] = []
    for module in model.modules():
        if isinstance(module, imports.torch.nn.BatchNorm2d):
            batch_norm_states.append((module, bool(module.training)))
            module.eval()
    return tuple(batch_norm_states)


def _restore_batch_norm_modules(
    batch_norm_states: tuple[tuple[Any, bool], ...],
) -> None:
    """恢复验证前 BatchNorm 的训练状态。"""

    for module, was_training in batch_norm_states:
        module.train(was_training)


def _normalize_history_items(value: object) -> list[dict[str, object]]:
    """把 checkpoint 中的指标历史归一成可继续追加的列表。"""

    if not isinstance(value, list):
        return []
    normalized_items: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            normalized_items.append(
                {str(key): current_value for key, current_value in item.items()}
            )
    return normalized_items


def _normalize_evaluated_epochs(value: object) -> tuple[int, ...]:
    """把 checkpoint 中的验证 epoch 列表归一成整数元组。"""

    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and item > 0)


def _build_checkpoint_bytes_from_state(
    *,
    imports: _TrainingImports,
    checkpoint_state: dict[str, object] | None,
) -> bytes:
    """把已缓存的 checkpoint 状态重新编码成二进制。"""

    if (
        isinstance(checkpoint_state, dict)
        and checkpoint_state.get("model_type") == "yolov8"
    ):
        return encode_yolov8_detection_checkpoint_state(
            torch_module=imports.torch,
            checkpoint_state=checkpoint_state,
        )
    if checkpoint_state is None:
        return b""
    buffer = io.BytesIO()
    imports.torch.save(checkpoint_state, buffer)
    return buffer.getvalue()


def _read_float_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    """从 extra_options 里读取浮点数配置。"""

    value = extra_options.get(key, default)
    if not isinstance(value, int | float):
        raise InvalidRequestError(
            "训练 extra_options 中的数值配置不合法",
            details={"option_key": key, "value": value},
        )
    return float(value)


def _read_bool_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    """从 extra_options 里读取布尔配置。"""

    value = extra_options.get(key, default)
    if not isinstance(value, bool):
        raise InvalidRequestError(
            "训练 extra_options 中的布尔配置不合法",
            details={"option_key": key, "value": value},
        )
    return bool(value)


def _read_int_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    """从 extra_options 里读取整数字段。"""

    value = extra_options.get(key, default)
    if not isinstance(value, int):
        raise InvalidRequestError(
            "训练 extra_options 中的整数配置不合法",
            details={"option_key": key, "value": value},
        )
    return int(value)


def _read_float_pair_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: tuple[float, float],
) -> tuple[float, float]:
    """从 extra_options 里读取长度为 2 的浮点区间。"""

    value = extra_options.get(key, default)
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise InvalidRequestError(
            "训练 extra_options 中的区间配置不合法",
            details={"option_key": key, "value": value},
        )
    left, right = value
    if not isinstance(left, int | float) or not isinstance(right, int | float):
        raise InvalidRequestError(
            "训练 extra_options 中的区间配置不合法",
            details={"option_key": key, "value": value},
        )
    left_value = float(left)
    right_value = float(right)
    if left_value <= 0.0 or right_value <= 0.0:
        raise InvalidRequestError(
            "训练 extra_options 中的区间配置必须为正数",
            details={"option_key": key, "value": value},
        )
    if left_value > right_value:
        left_value, right_value = right_value, left_value
    return (left_value, right_value)


def _resolve_detection_augmentation_options(
    extra_options: dict[str, object],
) -> _DetectionAugmentationOptions:
    """把 detection 训练增强相关 extra_options 解析为稳定配置。"""

    multi_scale_value = extra_options.get(
        "multi_scale",
        YOLOV8_DETECTION_DEFAULT_MULTI_SCALE,
    )
    multi_scale_enabled = (
        bool(multi_scale_value)
        if not isinstance(multi_scale_value, int | float)
        else float(multi_scale_value) > 0.0
    )
    multi_scale_default_range = (
        (1.0 - float(multi_scale_value), 1.0 + float(multi_scale_value))
        if isinstance(multi_scale_value, int | float) and float(multi_scale_value) > 0.0
        else YOLOV8_DETECTION_DEFAULT_MULTI_SCALE_RANGE
    )
    return _DetectionAugmentationOptions(
        flip_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "flip_prob",
                default=YOLOV8_DETECTION_DEFAULT_FLIP_PROB,
            )
        ),
        hsv_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "hsv_prob",
                default=YOLOV8_DETECTION_DEFAULT_HSV_PROB,
            )
        ),
        mosaic_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "mosaic_prob",
                default=YOLOV8_DETECTION_DEFAULT_MOSAIC_PROB,
            )
        ),
        mixup_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "mixup_prob",
                default=YOLOV8_DETECTION_DEFAULT_MIXUP_PROB,
            )
        ),
        enable_mixup=_read_bool_option(
            extra_options,
            "enable_mixup",
            default=YOLOV8_DETECTION_DEFAULT_ENABLE_MIXUP,
        ),
        affine_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "affine_prob",
                default=YOLOV8_DETECTION_DEFAULT_AFFINE_PROB,
            )
        ),
        degrees=max(
            0.0,
            _read_float_option(
                extra_options,
                "degrees",
                default=YOLOV8_DETECTION_DEFAULT_AFFINE_DEGREES,
            ),
        ),
        translate=max(
            0.0,
            _read_float_option(
                extra_options,
                "translate",
                default=YOLOV8_DETECTION_DEFAULT_AFFINE_TRANSLATE,
            ),
        ),
        scale=max(
            0.0,
            _read_float_option(
                extra_options,
                "scale",
                default=YOLOV8_DETECTION_DEFAULT_AFFINE_SCALE,
            ),
        ),
        shear=max(
            0.0,
            _read_float_option(
                extra_options,
                "shear",
                default=YOLOV8_DETECTION_DEFAULT_AFFINE_SHEAR,
            ),
        ),
        perspective=max(
            0.0,
            _read_float_option(
                extra_options,
                "perspective",
                default=YOLOV8_DETECTION_DEFAULT_AFFINE_PERSPECTIVE,
            ),
        ),
        mosaic_scale=_read_float_pair_option(
            extra_options,
            "mosaic_scale",
            default=YOLOV8_DETECTION_DEFAULT_MOSAIC_SCALE,
        ),
        mixup_scale=_read_float_pair_option(
            extra_options,
            "mixup_scale",
            default=YOLOV8_DETECTION_DEFAULT_MIXUP_SCALE,
        ),
        close_mosaic_epochs=max(
            0,
            int(
                _read_float_option(
                    extra_options,
                    "close_mosaic",
                    default=float(YOLOV8_DETECTION_DEFAULT_CLOSE_MOSAIC_EPOCHS),
                )
            ),
        ),
        multi_scale=multi_scale_enabled,
        multi_scale_range=_read_float_pair_option(
            extra_options,
            "multi_scale_range",
            default=multi_scale_default_range,
        ),
        multi_scale_stride=max(
            1,
            int(
                _read_float_option(
                    extra_options,
                    "multi_scale_stride",
                    default=float(YOLOV8_DETECTION_DEFAULT_MULTI_SCALE_STRIDE),
                )
            ),
        ),
    )


def _build_training_batch_for_epoch(
    *,
    imports: _TrainingImports,
    samples: list[Any],
    available_samples: tuple[Any, ...],
    base_input_size: tuple[int, int],
    epoch: int,
    max_epochs: int,
    device: str,
    runtime_precision: str,
    augmentation_options: _DetectionAugmentationOptions,
) -> tuple[Any, tuple[Any, ...]]:
    """按当前 epoch 解析增强和输入尺寸后构建 YOLOv8 detection batch。"""

    effective_options = _resolve_detection_augmentation_for_epoch(
        augmentation_options=augmentation_options,
        epoch=epoch,
        max_epochs=max_epochs,
    )
    batch_input_size = _resolve_detection_batch_input_size(
        base_input_size=base_input_size,
        augmentation_options=effective_options,
    )
    return build_yolov8_detection_training_batch(
        imports=imports,
        samples=samples,
        input_size=batch_input_size,
        device=device,
        runtime_precision=runtime_precision,
        augment_training=True,
        available_samples=available_samples,
        augmentation_options=effective_options,
    )


def _resolve_detection_augmentation_for_epoch(
    *,
    augmentation_options: _DetectionAugmentationOptions,
    epoch: int,
    max_epochs: int,
) -> _DetectionAugmentationOptions:
    """按 close_mosaic 规则解析当前 epoch 实际生效的增强配置。"""

    close_epochs = int(augmentation_options.close_mosaic_epochs)
    if close_epochs <= 0 or int(epoch) < max(0, int(max_epochs) - close_epochs + 1):
        return augmentation_options
    return _DetectionAugmentationOptions(
        flip_prob=augmentation_options.flip_prob,
        hsv_prob=augmentation_options.hsv_prob,
        mosaic_prob=0.0,
        mixup_prob=0.0,
        enable_mixup=False,
        affine_prob=augmentation_options.affine_prob,
        degrees=augmentation_options.degrees,
        translate=augmentation_options.translate,
        scale=augmentation_options.scale,
        shear=augmentation_options.shear,
        perspective=augmentation_options.perspective,
        mosaic_scale=augmentation_options.mosaic_scale,
        mixup_scale=augmentation_options.mixup_scale,
        close_mosaic_epochs=augmentation_options.close_mosaic_epochs,
        multi_scale=augmentation_options.multi_scale,
        multi_scale_range=augmentation_options.multi_scale_range,
        multi_scale_stride=augmentation_options.multi_scale_stride,
    )


def _resolve_detection_batch_input_size(
    *,
    base_input_size: tuple[int, int],
    augmentation_options: _DetectionAugmentationOptions,
) -> tuple[int, int]:
    """按 multi-scale 配置解析当前 batch 的输入尺寸。"""

    if not augmentation_options.multi_scale:
        return base_input_size
    scale_min, scale_max = augmentation_options.multi_scale_range
    scale_value = random.uniform(float(scale_min), float(scale_max))
    stride = max(1, int(augmentation_options.multi_scale_stride))
    height = max(stride, int(round(int(base_input_size[0]) * scale_value / stride)) * stride)
    width = max(stride, int(round(int(base_input_size[1]) * scale_value / stride)) * stride)
    return (height, width)


def _serialize_detection_augmentation_options(
    options: _DetectionAugmentationOptions,
) -> dict[str, object]:
    """把 detection 增强配置转换为可写入结果和 checkpoint 的字典。"""

    return {
        "flip_prob": options.flip_prob,
        "hsv_prob": options.hsv_prob,
        "mosaic_prob": options.mosaic_prob,
        "mixup_prob": options.mixup_prob,
        "enable_mixup": options.enable_mixup,
        "affine_prob": options.affine_prob,
        "degrees": options.degrees,
        "translate": options.translate,
        "scale": options.scale,
        "shear": options.shear,
        "perspective": options.perspective,
        "mosaic_scale": list(options.mosaic_scale),
        "mixup_scale": list(options.mixup_scale),
        "close_mosaic_epochs": options.close_mosaic_epochs,
        "multi_scale": options.multi_scale,
        "multi_scale_range": list(options.multi_scale_range),
        "multi_scale_stride": options.multi_scale_stride,
    }


def _clamp_probability(value: float) -> float:
    """把概率值裁剪到 [0, 1]。"""

    return max(0.0, min(1.0, float(value)))

