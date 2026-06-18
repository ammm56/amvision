"""YOLO 主线 detection 共享训练执行模块。"""

from __future__ import annotations

import io
import json
import math
import random
from collections.abc import Callable
from contextlib import nullcontext, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_DETECTION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.detection_postprocess import (
    DEFAULT_END2END_MAX_DETECTIONS,
    DETECTION_POSTPROCESS_MODE_END2END_TOPK,
    DETECTION_POSTPROCESS_MODE_NMS,
    postprocess_detection_prediction_array,
)
from backend.service.application.models.yolo_core_common.assigners import (
    assign_detection_targets,
    box_iou_aligned,
)
from backend.service.application.models.yolo_core_common.decode import (
    decode_detection_training_predictions,
)
from backend.service.application.models.yolo_core_common.losses import (
    distribution_focal_loss,
)
from backend.service.application.models.yolo_core_common.targets import (
    bbox_xyxy_to_distances,
)
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_detection_training_batch,
)
from backend.service.application.models.yolov8_core.training import (
    YoloV8DetectionResumeValidationRequest,
    YoloV8DetectionTrainingBatchProgress,
    build_yolov8_detection_checkpoint_state,
    build_yolov8_detection_epoch_checkpoint_update,
    build_yolov8_detection_training_savepoint_payload,
    build_yolov8_detection_training_runtime,
    compute_yolov8_detection_training_loss,
    encode_yolov8_detection_checkpoint_state,
    evaluate_yolov8_detection_validation_losses,
    is_yolov8_detection_core_model,
    move_yolov8_optimizer_state_to_device,
    resolve_yolov8_detection_best_metric_update,
    resolve_yolov8_detection_epoch_control,
    serialize_yolov8_detection_best_metric_value,
    should_run_yolov8_detection_validation,
    plan_yolov8_detection_training_execution,
    prepare_yolov8_detection_training_data_context,
    run_yolov8_detection_training_epoch,
    validate_yolov8_detection_resume_checkpoint,
)
from backend.service.application.models.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
    load_yolo_primary_checkpoint,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLO_PRIMARY_IMPLEMENTATION_MODE = "yolo-primary-detection"
YOLO_PRIMARY_DEFAULT_INPUT_SIZE = (640, 640)
YOLO_PRIMARY_DEFAULT_BATCH_SIZE = 1
YOLO_PRIMARY_DEFAULT_MAX_EPOCHS = 1
YOLO_PRIMARY_DEFAULT_EVALUATION_INTERVAL = 5
YOLO_PRIMARY_DEFAULT_EVAL_CONFIDENCE_THRESHOLD = 0.01
YOLO_PRIMARY_DEFAULT_EVAL_NMS_THRESHOLD = 0.65
YOLO_PRIMARY_DEFAULT_ASSIGN_TOPK = 10
YOLO_PRIMARY_DEFAULT_CLASS_LOSS_WEIGHT = 0.5
YOLO_PRIMARY_DEFAULT_BOX_LOSS_WEIGHT = 7.5
YOLO_PRIMARY_DEFAULT_DFL_LOSS_WEIGHT = 1.5
YOLO_PRIMARY_DEFAULT_ASSIGN_ALPHA = 0.5
YOLO_PRIMARY_DEFAULT_ASSIGN_BETA = 6.0
YOLO_PRIMARY_DEFAULT_MIN_LR_RATIO = 0.01
YOLO_PRIMARY_DEFAULT_GRAD_CLIP_NORM = 10.0
YOLO_PRIMARY_DEFAULT_FLIP_PROB = 0.0
YOLO_PRIMARY_DEFAULT_HSV_PROB = 0.0
YOLO_PRIMARY_DEFAULT_MOSAIC_PROB = 0.0
YOLO_PRIMARY_DEFAULT_MIXUP_PROB = 0.0
YOLO_PRIMARY_DEFAULT_ENABLE_MIXUP = False
YOLO_PRIMARY_DEFAULT_AFFINE_DEGREES = 10.0
YOLO_PRIMARY_DEFAULT_AFFINE_TRANSLATE = 0.1
YOLO_PRIMARY_DEFAULT_AFFINE_SHEAR = 2.0
YOLO_PRIMARY_DEFAULT_MOSAIC_SCALE = (0.1, 2.0)
YOLO_PRIMARY_DEFAULT_MIXUP_SCALE = (0.5, 1.5)


@dataclass(frozen=True)
class YoloPrimaryTrainingBatchProgress:
    """描述单个训练 batch 完成后的进度快照。"""

    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class YoloPrimaryTrainingEpochProgress:
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
class YoloPrimaryTrainingControlCommand:
    """描述单轮训练结束后由上层返回给训练循环的控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class YoloPrimaryTrainingSavePoint:
    """描述训练在某个 epoch 边界导出的可恢复 savepoint。"""

    epoch: int
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None = None
    best_metric_name: str = ""
    best_metric_value: float | None = None


@dataclass(frozen=True)
class YoloPrimaryDetectionTrainingExecutionRequest:
    """描述一次 YOLO 主线 detection 共享训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str
    model_type: str = "yolov8"
    implementation_mode: str = YOLO_PRIMARY_IMPLEMENTATION_MODE
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
    batch_callback: Callable[[YoloPrimaryTrainingBatchProgress], None] | None = None
    epoch_callback: Callable[[YoloPrimaryTrainingEpochProgress], YoloPrimaryTrainingControlCommand | None] | None = None
    savepoint_callback: Callable[[YoloPrimaryTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class YoloPrimaryDetectionTrainingExecutionResult:
    """描述一次 YOLO 主线 detection 共享训练执行结果。"""

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
    """描述 YOLO 主线 detection 训练所需的第三方依赖对象。"""

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
    degrees: float
    translate: float
    shear: float
    mosaic_scale: tuple[float, float]
    mixup_scale: tuple[float, float]


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


class YoloPrimaryTrainingPausedError(Exception):
    """表示训练在 epoch 边界按请求完成保存后进入 paused 状态。"""

    def __init__(self, savepoint: YoloPrimaryTrainingSavePoint) -> None:
        super().__init__("yolo primary detection training paused")
        self.savepoint = savepoint


class YoloPrimaryTrainingTerminatedError(Exception):
    """表示训练在 epoch 边界按请求终止。"""

    def __init__(self) -> None:
        super().__init__("yolo primary detection training terminated")


def run_yolo_primary_detection_training(
    request: YoloPrimaryDetectionTrainingExecutionRequest,
) -> YoloPrimaryDetectionTrainingExecutionResult:
    """执行一轮项目内 YOLO 主线 detection 共享训练。"""

    imports = _require_training_imports()
    manifest_payload = dict(request.manifest_payload)
    yolov8_data_context = None
    if request.model_type == "yolov8":
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
        validation_category_names = yolov8_data_context.validation_category_names
        validation_category_ids = yolov8_data_context.validation_category_ids
    else:
        resolved_splits = _resolve_non_yolov8_detection_splits(
            dataset_storage=request.dataset_storage,
            imports=imports,
            manifest_payload=manifest_payload,
        )
        train_split = _resolve_non_yolov8_train_split(resolved_splits)
        validation_split = _resolve_non_yolov8_validation_split(resolved_splits)
        train_samples, category_names, category_ids = _load_non_yolov8_training_samples(
            imports=imports,
            split=train_split,
        )
        validation_samples: tuple[_ResolvedTrainingSample, ...] = ()
        validation_category_ids: tuple[int, ...] = ()
        validation_category_names: tuple[str, ...] | None = None
        if validation_split is not None:
            validation_samples, validation_category_names, validation_category_ids = _load_non_yolov8_training_samples(
                imports=imports,
                split=validation_split,
            )
            if validation_category_names != category_names:
                raise InvalidRequestError(
                    "验证 split 的 categories 与训练 split 不一致",
                    details={
                        "train_categories": list(category_names),
                        "validation_categories": list(validation_category_names),
                    },
                )
            if validation_category_ids != category_ids:
                raise InvalidRequestError(
                    "验证 split 的 category_id 映射与训练 split 不一致",
                    details={
                        "train_category_ids": list(category_ids),
                        "validation_category_ids": list(validation_category_ids),
                    },
                )
    input_size = _resolve_input_size(request.input_size)
    batch_size = max(1, int(request.batch_size or YOLO_PRIMARY_DEFAULT_BATCH_SIZE))
    max_epochs = max(1, int(request.max_epochs or YOLO_PRIMARY_DEFAULT_MAX_EPOCHS))
    evaluation_interval = max(
        1,
        int(request.evaluation_interval or YOLO_PRIMARY_DEFAULT_EVALUATION_INTERVAL),
    )
    extra_options = dict(request.extra_options or {})
    if request.model_type != "yolov8" and not train_samples:
        raise InvalidRequestError("训练 split 不包含可用样本")

    device, gpu_count, device_ids, distributed_mode, runtime_precision = _resolve_runtime(
        imports=imports,
        requested_gpu_count=request.gpu_count,
        requested_precision=request.precision,
    )
    learning_rate = _read_float_option(extra_options, "learning_rate", default=1e-3)
    weight_decay = _read_float_option(extra_options, "weight_decay", default=1e-4)
    class_loss_weight = _read_float_option(
        extra_options,
        "class_loss_weight",
        default=YOLO_PRIMARY_DEFAULT_CLASS_LOSS_WEIGHT,
    )
    box_loss_weight = _read_float_option(
        extra_options,
        "box_loss_weight",
        default=YOLO_PRIMARY_DEFAULT_BOX_LOSS_WEIGHT,
    )
    dfl_loss_weight = _read_float_option(
        extra_options,
        "dfl_loss_weight",
        default=YOLO_PRIMARY_DEFAULT_DFL_LOSS_WEIGHT,
    )
    evaluation_confidence_threshold = _read_float_option(
        extra_options,
        "evaluation_confidence_threshold",
        default=YOLO_PRIMARY_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
    )
    evaluation_nms_threshold = _read_float_option(
        extra_options,
        "evaluation_nms_threshold",
        default=YOLO_PRIMARY_DEFAULT_EVAL_NMS_THRESHOLD,
    )
    assign_topk = max(
        1,
        _read_int_option(extra_options, "assign_topk", default=YOLO_PRIMARY_DEFAULT_ASSIGN_TOPK),
    )
    assign_alpha = _read_float_option(
        extra_options,
        "assign_alpha",
        default=YOLO_PRIMARY_DEFAULT_ASSIGN_ALPHA,
    )
    assign_beta = _read_float_option(
        extra_options,
        "assign_beta",
        default=YOLO_PRIMARY_DEFAULT_ASSIGN_BETA,
    )
    min_lr_ratio = _read_float_option(
        extra_options,
        "min_lr_ratio",
        default=YOLO_PRIMARY_DEFAULT_MIN_LR_RATIO,
    )
    grad_clip_norm = _read_float_option(
        extra_options,
        "grad_clip_norm",
        default=YOLO_PRIMARY_DEFAULT_GRAD_CLIP_NORM,
    )
    augmentation_options = _resolve_detection_augmentation_options(extra_options)
    validation_split_name = validation_split.name if validation_split is not None else None

    model = build_yolo_primary_detection_model(
        model_type=request.model_type,
        model_scale=request.model_scale,
        num_classes=len(category_names),
    )
    
    # 检测模型是否启用端到端训练
    is_end2end = getattr(model, "end2end", False)
    
    # 端到端训练的权重调度器
    e2e_o2m_weight = 0.8  # one2many 初始权重
    e2e_o2o_weight = 0.2  # one2one 初始权重
    e2e_o2m_initial = 0.8
    e2e_o2m_final = 0.1
    
    def update_e2e_weights(epoch: int, total_epochs: int) -> None:
        """更新端到端训练的分支权重。
        
        训练初期 one2many 主导（提供充足梯度），
        训练末期 one2one 主导（确保推理精度）。
        """
        nonlocal e2e_o2m_weight, e2e_o2o_weight
        if total_epochs <= 1:
            progress = 1.0
        else:
            progress = epoch / (total_epochs - 1)
        e2e_o2m_weight = e2e_o2m_initial + (e2e_o2m_final - e2e_o2m_initial) * progress
        e2e_o2o_weight = 1.0 - e2e_o2m_weight
    
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

    parameter_count = sum(
        int(parameter.numel())
        for parameter in model.parameters()
    )
    if request.model_type == "yolov8":
        training_runtime = build_yolov8_detection_training_runtime(
            torch_module=imports.torch,
            model=model,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            max_epochs=max_epochs,
            min_lr_ratio=min_lr_ratio,
            device=device,
            runtime_precision=runtime_precision,
        )
        optimizer = training_runtime.optimizer
        scheduler = training_runtime.scheduler
        scaler = training_runtime.scaler
    else:
        optimizer = imports.torch.optim.AdamW(
            model.parameters(),
            lr=learning_rate,
            weight_decay=weight_decay,
        )
        scheduler = imports.torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=max_epochs,
            eta_min=learning_rate * min_lr_ratio,
        )
        scaler_enabled = device.startswith("cuda") and runtime_precision == "fp16"
        amp_module = getattr(imports.torch, "amp", None)
        grad_scaler_cls = getattr(amp_module, "GradScaler", None) if amp_module is not None else None
        if grad_scaler_cls is not None:
            scaler = grad_scaler_cls("cuda", enabled=scaler_enabled)
        else:
            scaler = imports.torch.cuda.amp.GradScaler(enabled=scaler_enabled)
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
        if request.model_type == "yolov8":
            move_yolov8_optimizer_state_to_device(optimizer=optimizer, device=device)
        else:
            _move_optimizer_state_to_device(optimizer=optimizer, device=device)
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
        list(resume_state.evaluated_epochs)
        if resume_state is not None
        else []
    )
    if request.model_type == "yolov8":
        if yolov8_data_context is None:
            raise ServiceConfigurationError("YOLOv8 detection 训练缺少 data context")
        execution_plan = plan_yolov8_detection_training_execution(
            data_context=yolov8_data_context,
            batch_size=batch_size,
            max_epochs=max_epochs,
            resume_epoch=resume_state.resume_epoch if resume_state is not None else 0,
            resume_best_metric_name=(resume_state.best_metric_name if resume_state is not None else None),
            resume_best_metric_value=(resume_state.best_metric_value if resume_state is not None else None),
        )
        has_validation = execution_plan.has_validation
        best_metric_name = execution_plan.best_metric_name
        best_metric_value = execution_plan.best_metric_value
        total_iterations = execution_plan.total_iterations
        global_iteration = execution_plan.initial_global_iteration
    else:
        has_validation = validation_split is not None and bool(validation_samples)
        best_metric_name = (
            resume_state.best_metric_name
            if resume_state is not None and resume_state.best_metric_name.strip()
            else ("map50_95" if has_validation else "train_loss")
        )
        best_metric_value = (
            resume_state.best_metric_value
            if resume_state is not None and resume_state.best_metric_value is not None
            else (float("-inf") if has_validation else float("inf"))
        )
        total_iterations = max_epochs * max(1, (len(train_samples) + batch_size - 1) // batch_size)
        resume_epoch_for_iterations = resume_state.resume_epoch if resume_state is not None else 0
        if resume_epoch_for_iterations >= max_epochs:
            raise InvalidRequestError(
                "resume checkpoint 已经达到或超过本次训练请求的最大 epoch",
                details={"resume_epoch": resume_epoch_for_iterations, "max_epochs": max_epochs},
            )
        global_iteration = resume_epoch_for_iterations * max(
            1,
            (len(train_samples) + batch_size - 1) // batch_size,
        )
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
        # 更新端到端训练权重
        if is_end2end:
            update_e2e_weights(epoch - 1, max_epochs)
        
        if request.model_type == "yolov8":
            def on_yolov8_batch_progress(
                progress: YoloV8DetectionTrainingBatchProgress,
            ) -> None:
                """把 YOLOv8 core batch 进度转成平台训练进度对象。"""

                if request.batch_callback is None:
                    return
                request.batch_callback(
                    YoloPrimaryTrainingBatchProgress(
                        epoch=progress.epoch,
                        max_epochs=progress.max_epochs,
                        iteration=progress.iteration,
                        max_iterations=progress.max_iterations,
                        global_iteration=progress.global_iteration,
                        total_iterations=progress.total_iterations,
                        input_size=progress.input_size,
                        learning_rate=progress.learning_rate,
                        train_metrics=progress.train_metrics,
                    )
                )

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
                autocast_context=autocast_context,
                build_batch=lambda sample_batch, available_samples: build_yolov8_detection_training_batch(
                    imports=imports,
                    samples=sample_batch,
                    input_size=input_size,
                    device=device,
                    runtime_precision=runtime_precision,
                    augment_training=True,
                    available_samples=available_samples,
                    augmentation_options=augmentation_options,
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
                    on_yolov8_batch_progress
                    if request.batch_callback is not None
                    else None
                ),
            )
            global_iteration = epoch_result.global_iteration
            train_metrics = dict(epoch_result.train_metrics)
        else:
            shuffled_samples = list(train_samples)
            random.shuffle(shuffled_samples)
            epoch_losses = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
            if is_end2end:
                epoch_losses["one2many_loss"] = 0.0
                epoch_losses["one2one_loss"] = 0.0
            max_iterations = max(1, (len(shuffled_samples) + batch_size - 1) // batch_size)
            model.train()

            for iteration, sample_batch in enumerate(_iter_batches(shuffled_samples, batch_size), start=1):
                global_iteration += 1
                images, batch_targets = _build_non_yolov8_training_batch(
                    imports=imports,
                    samples=sample_batch,
                    input_size=input_size,
                    device=device,
                    runtime_precision=runtime_precision,
                    augment_training=True,
                    available_samples=tuple(shuffled_samples),
                    augmentation_options=augmentation_options,
                )
                optimizer.zero_grad(set_to_none=True)
                with autocast_context():
                    model_outputs = model(images)

                    if is_end2end:
                        # 端到端训练：使用双分支损失
                        e2e_outputs = _unwrap_e2e_detection_outputs(model_outputs)
                        loss_components = _compute_e2e_detection_loss(
                            imports=imports,
                            model=model,
                            raw_outputs=e2e_outputs,
                            batch_targets=batch_targets,
                            num_classes=len(category_names),
                            class_loss_weight=class_loss_weight,
                            box_loss_weight=box_loss_weight,
                            dfl_loss_weight=dfl_loss_weight,
                            assign_topk=assign_topk,
                            assign_alpha=assign_alpha,
                            assign_beta=assign_beta,
                            e2e_o2m_weight=e2e_o2m_weight,
                            e2e_o2o_weight=e2e_o2o_weight,
                        )
                    else:
                        # 标准训练：使用单分支损失
                        raw_outputs = _unwrap_detection_outputs(model_outputs)
                        loss_components = _compute_detection_loss(
                            imports=imports,
                            model=model,
                            raw_outputs=raw_outputs,
                            batch_targets=batch_targets,
                            num_classes=len(category_names),
                            class_loss_weight=class_loss_weight,
                            box_loss_weight=box_loss_weight,
                            dfl_loss_weight=dfl_loss_weight,
                            assign_topk=assign_topk,
                            assign_alpha=assign_alpha,
                            assign_beta=assign_beta,
                        )
                    loss = loss_components["loss"]
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                if grad_clip_norm > 0:
                    imports.torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm)
                scaler.step(optimizer)
                scaler.update()

                for key in epoch_losses:
                    if key in loss_components:
                        epoch_losses[key] += float(loss_components[key].detach().item())

                if request.batch_callback is not None:
                    train_metrics_batch = {
                        "loss": float(loss_components["loss"].detach().item()),
                        "class_loss": float(loss_components["class_loss"].detach().item()),
                        "box_loss": float(loss_components["box_loss"].detach().item()),
                        "dfl_loss": float(loss_components["dfl_loss"].detach().item()),
                    }
                    if is_end2end:
                        train_metrics_batch["one2many_loss"] = float(
                            loss_components["one2many_loss"].detach().item()
                        )
                        train_metrics_batch["one2one_loss"] = float(
                            loss_components["one2one_loss"].detach().item()
                        )
                        train_metrics_batch["e2e_o2m_weight"] = e2e_o2m_weight
                        train_metrics_batch["e2e_o2o_weight"] = e2e_o2o_weight

                    request.batch_callback(
                        YoloPrimaryTrainingBatchProgress(
                            epoch=epoch,
                            max_epochs=max_epochs,
                            iteration=iteration,
                            max_iterations=max_iterations,
                            global_iteration=global_iteration,
                            total_iterations=total_iterations,
                            input_size=input_size,
                            learning_rate=float(optimizer.param_groups[0]["lr"]),
                            train_metrics=train_metrics_batch,
                        )
                    )

            train_metrics = {
                key: round(value / max_iterations, 6)
                for key, value in epoch_losses.items()
            }
        train_metrics["epoch"] = epoch
        metrics_history.append(train_metrics)

        validation_ran = (
            should_run_yolov8_detection_validation(
                epoch=epoch,
                max_epochs=max_epochs,
                evaluation_interval=evaluation_interval,
                validation_sample_count=len(validation_samples),
            )
            if request.model_type == "yolov8"
            else (
                validation_split is not None
                and bool(validation_samples)
                and (epoch == max_epochs or epoch % evaluation_interval == 0)
            )
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
                annotation_file=validation_split.annotation_file if validation_split is not None else None,
                annotation_payload=validation_split.annotation_payload if validation_split is not None else None,
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
                use_yolov8_core_data=request.model_type == "yolov8",
            )
            validation_history.append(validation_snapshot)
            validation_metrics = {
                "loss": float(validation_snapshot["loss"]),
                "map50": float(validation_snapshot["map50"]),
                "map50_95": float(validation_snapshot["map50_95"]),
            }
            evaluated_epochs.append(epoch)
            current_metric_value = validation_metrics[best_metric_name]

        if request.model_type == "yolov8":
            best_metric_update = resolve_yolov8_detection_best_metric_update(
                validation_ran=validation_ran,
                current_metric_value=current_metric_value,
                train_loss=float(train_metrics["loss"]),
                best_metric_value=best_metric_value,
            )
            improved_best = best_metric_update.improved
            candidate_best_metric_value = best_metric_update.candidate_value
        else:
            improved_best = False
            candidate_best_metric_value = best_metric_value
            if validation_ran and current_metric_value is not None:
                if current_metric_value >= best_metric_value:
                    improved_best = True
                    candidate_best_metric_value = current_metric_value
            elif train_metrics["loss"] <= best_metric_value:
                improved_best = True
                candidate_best_metric_value = train_metrics["loss"]

        scheduler.step()
        if request.model_type == "yolov8":
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
        else:
            previous_best_checkpoint_state = (
                _load_checkpoint_state_from_bytes(imports=imports, checkpoint_bytes=best_checkpoint_bytes)
                if best_checkpoint_bytes
                else None
            )
            current_checkpoint_state = _build_checkpoint_state(
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
                    evaluation_confidence_threshold
                    if validation_split is not None and bool(validation_samples)
                    else None
                ),
                evaluation_nms_threshold=(
                    evaluation_nms_threshold
                    if validation_split is not None and bool(validation_samples)
                    else None
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
                best_metric_value=candidate_best_metric_value,
                best_checkpoint_state=previous_best_checkpoint_state,
            )
            if improved_best:
                current_best_checkpoint_state = dict(current_checkpoint_state)
                current_best_checkpoint_state["best_checkpoint_state"] = None
                current_checkpoint_state["best_checkpoint_state"] = current_best_checkpoint_state
                best_metric_value = candidate_best_metric_value
                best_checkpoint_bytes = _build_checkpoint_bytes_from_state(
                    imports=imports,
                    checkpoint_state=current_best_checkpoint_state,
                )
            latest_checkpoint_bytes = _build_checkpoint_bytes_from_state(
                imports=imports,
                checkpoint_state=current_checkpoint_state,
            )

        control_command = None
        if request.epoch_callback is not None:
            control_command = request.epoch_callback(
                YoloPrimaryTrainingEpochProgress(
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
                    best_metric_value=(
                        serialize_yolov8_detection_best_metric_value(
                            has_validation=has_validation,
                            best_metric_value=best_metric_value,
                        )
                        if request.model_type == "yolov8"
                        else (
                            None
                            if (
                                (validation_split is not None and best_metric_value == float("-inf"))
                                or (validation_split is None and best_metric_value == float("inf"))
                            )
                            else round(best_metric_value, 6)
                        )
                    ),
                )
            )
        if request.model_type == "yolov8":
            control_decision = resolve_yolov8_detection_epoch_control(
                save_checkpoint_requested=(
                    control_command.save_checkpoint if control_command is not None else False
                ),
                pause_training_requested=(
                    control_command.pause_training if control_command is not None else False
                ),
                terminate_training_requested=(
                    control_command.terminate_training if control_command is not None else False
                ),
            )
            should_write_savepoint = control_decision.save_checkpoint
            should_pause_training = control_decision.pause_training
            should_terminate_training = control_decision.terminate_training
        else:
            should_write_savepoint = control_command is not None and (
                control_command.save_checkpoint or control_command.pause_training
            )
            should_pause_training = control_command is not None and control_command.pause_training
            should_terminate_training = (
                control_command is not None and control_command.terminate_training
            )
        if should_write_savepoint:
            if request.model_type == "yolov8":
                savepoint_payload = build_yolov8_detection_training_savepoint_payload(
                    epoch=epoch,
                    latest_checkpoint_bytes=latest_checkpoint_bytes,
                    best_checkpoint_bytes=best_checkpoint_bytes,
                    best_metric_name=best_metric_name,
                    best_metric_value=best_metric_value,
                    has_validation=has_validation,
                )
                savepoint = YoloPrimaryTrainingSavePoint(
                    epoch=savepoint_payload.epoch,
                    latest_checkpoint_bytes=savepoint_payload.latest_checkpoint_bytes,
                    best_checkpoint_bytes=savepoint_payload.best_checkpoint_bytes,
                    best_metric_name=savepoint_payload.best_metric_name,
                    best_metric_value=savepoint_payload.best_metric_value,
                )
            else:
                savepoint = YoloPrimaryTrainingSavePoint(
                    epoch=epoch,
                    latest_checkpoint_bytes=latest_checkpoint_bytes,
                    best_checkpoint_bytes=best_checkpoint_bytes or latest_checkpoint_bytes,
                    best_metric_name=best_metric_name,
                    best_metric_value=(
                        None
                        if (
                            (validation_split is not None and best_metric_value == float("-inf"))
                            or (validation_split is None and best_metric_value == float("inf"))
                        )
                        else round(best_metric_value, 6)
                    ),
                )
            if request.savepoint_callback is not None:
                request.savepoint_callback(savepoint)
            if should_pause_training:
                raise YoloPrimaryTrainingPausedError(savepoint)
        if should_terminate_training:
            raise YoloPrimaryTrainingTerminatedError()

    if not best_checkpoint_bytes:
        best_checkpoint_bytes = latest_checkpoint_bytes
    if validation_split is not None and best_metric_value == float("-inf"):
        best_metric_value = 0.0
    if validation_split is None and best_metric_value == float("inf"):
        best_metric_value = 0.0

    evaluation_postprocess_mode = (
        DETECTION_POSTPROCESS_MODE_END2END_TOPK
        if is_end2end
        else DETECTION_POSTPROCESS_MODE_NMS
    )
    evaluation_max_detections = (
        DEFAULT_END2END_MAX_DETECTIONS
        if evaluation_postprocess_mode == DETECTION_POSTPROCESS_MODE_END2END_TOPK
        else None
    )

    validation_metrics_payload = {
        "enabled": validation_split is not None and bool(validation_samples),
        "evaluation_interval": evaluation_interval,
        "split_name": validation_split.name if validation_split is not None else None,
        "sample_count": len(validation_samples),
        "confidence_threshold": (
            evaluation_confidence_threshold if validation_split is not None and bool(validation_samples) else None
        ),
        "nms_threshold": (
            evaluation_nms_threshold
            if validation_split is not None
            and bool(validation_samples)
            and evaluation_postprocess_mode == DETECTION_POSTPROCESS_MODE_NMS
            else None
        ),
        "postprocess_mode": (
            evaluation_postprocess_mode if validation_split is not None and bool(validation_samples) else None
        ),
        "max_detections": (
            evaluation_max_detections if validation_split is not None and bool(validation_samples) else None
        ),
        "best_metric_name": best_metric_name if validation_split is not None and bool(validation_samples) else None,
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
        "validation_split_name": validation_split.name if validation_split is not None else None,
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
            "name": "AdamW",
            "learning_rate": learning_rate,
            "weight_decay": weight_decay,
        },
        "scheduler": {
            "name": "CosineAnnealingLR",
            "min_lr_ratio": min_lr_ratio,
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
        "augmentation": _serialize_detection_augmentation_options(
            augmentation_options
        ),
    }
    return YoloPrimaryDetectionTrainingExecutionResult(
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
        validation_split_name=validation_split.name if validation_split is not None else None,
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


def _resolve_non_yolov8_detection_splits(
    *,
    dataset_storage: LocalDatasetStorage,
    imports: _TrainingImports,
    manifest_payload: dict[str, object],
) -> tuple[_ResolvedDetectionSplit, ...]:
    """从导出 manifest 里解析非 YOLOv8 暂存路径使用的 detection split。"""

    format_id = str(manifest_payload.get("format_id") or COCO_DETECTION_DATASET_FORMAT).strip()
    if format_id == YOLO_DETECTION_DATASET_FORMAT:
        return _resolve_non_yolov8_yolo_detection_splits(
            dataset_storage=dataset_storage,
            imports=imports,
            manifest_payload=manifest_payload,
        )
    return _resolve_non_yolov8_coco_detection_splits(
        dataset_storage=dataset_storage,
        manifest_payload=manifest_payload,
    )


def _resolve_non_yolov8_coco_detection_splits(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> tuple[_ResolvedDetectionSplit, ...]:
    """从导出 manifest 里解析非 YOLOv8 暂存路径使用的 COCO detection split。"""

    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("训练输入 manifest 缺少 splits 定义")
    resolved_splits: list[_ResolvedDetectionSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name") or "").strip()
        image_root = str(split_item.get("image_root") or "").strip()
        annotation_file = str(split_item.get("annotation_file") or "").strip()
        if not split_name or not image_root or not annotation_file:
            continue
        annotation_path = dataset_storage.resolve(annotation_file)
        image_root_path = dataset_storage.resolve(image_root)
        if not annotation_path.is_file():
            raise InvalidRequestError(
                "训练输入 split 缺少 annotation 文件",
                details={"split_name": split_name, "annotation_file": annotation_file},
            )
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "训练输入 split 缺少图片目录",
                details={"split_name": split_name, "image_root": image_root},
            )
        annotation_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
        image_items = annotation_payload.get("images", [])
        sample_count = len(image_items) if isinstance(image_items, list) else 0
        resolved_splits.append(
            _ResolvedDetectionSplit(
                name=split_name,
                image_root=image_root_path,
                sample_count=sample_count,
                annotation_payload=annotation_payload,
                annotation_file=annotation_path,
            )
        )
    if not resolved_splits:
        raise InvalidRequestError("训练输入 manifest 没有可用的 split")
    return tuple(resolved_splits)


def _resolve_non_yolov8_yolo_detection_splits(
    *,
    dataset_storage: LocalDatasetStorage,
    imports: _TrainingImports,
    manifest_payload: dict[str, object],
) -> tuple[_ResolvedDetectionSplit, ...]:
    """从导出 manifest 里解析非 YOLOv8 暂存路径使用的 YOLO detection split。"""

    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("训练输入 manifest 缺少 splits 定义")
    category_names_payload = manifest_payload.get("category_names")
    category_names = tuple(
        normalized_name
        for item in (category_names_payload if isinstance(category_names_payload, list | tuple) else ())
        if (normalized_name := str(item).strip())
    )

    resolved_splits: list[_ResolvedDetectionSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name") or "").strip()
        image_root = str(split_item.get("image_root") or "").strip()
        annotation_file = str(split_item.get("annotation_file") or "").strip()
        label_root = str(split_item.get("label_root") or "").strip()
        if not split_name or not image_root:
            continue
        image_root_path = dataset_storage.resolve(image_root)
        if annotation_file:
            annotation_path = dataset_storage.resolve(annotation_file)
            if not annotation_path.is_file():
                raise InvalidRequestError(
                    "训练输入 split 缺少 annotation 文件",
                    details={"split_name": split_name, "annotation_file": annotation_file},
                )
            if not image_root_path.is_dir():
                raise InvalidRequestError(
                    "训练输入 split 缺少图片目录",
                    details={"split_name": split_name, "image_root": image_root},
                )
            annotation_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
            image_items = annotation_payload.get("images", [])
            sample_count = len(image_items) if isinstance(image_items, list) else 0
            resolved_splits.append(
                _ResolvedDetectionSplit(
                    name=split_name,
                    image_root=image_root_path,
                    sample_count=sample_count,
                    annotation_payload=annotation_payload,
                    annotation_file=annotation_path,
                )
            )
            continue
        if not label_root:
            continue
        if not category_names:
            raise InvalidRequestError("YOLO detection 训练输入缺少有效的 category_names")
        label_root_path = dataset_storage.resolve(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "训练输入 split 缺少图片目录",
                details={"split_name": split_name, "image_root": image_root},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "训练输入 split 缺少标签目录",
                details={"split_name": split_name, "label_root": label_root},
            )
        annotation_payload = _build_coco_annotation_payload_from_yolo_detection_split(
            imports=imports,
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=category_names,
        )
        image_items = annotation_payload.get("images", [])
        sample_count = len(image_items) if isinstance(image_items, list) else 0
        resolved_splits.append(
            _ResolvedDetectionSplit(
                name=split_name,
                image_root=image_root_path,
                sample_count=sample_count,
                annotation_payload=annotation_payload,
            )
        )
    if not resolved_splits:
        raise InvalidRequestError("训练输入 manifest 没有可用的 split")
    return tuple(resolved_splits)


def _resolve_non_yolov8_train_split(
    resolved_splits: tuple[_ResolvedDetectionSplit, ...],
) -> _ResolvedDetectionSplit:
    """优先解析非 YOLOv8 暂存路径使用的 train split。"""

    for split in resolved_splits:
        if split.name.lower() == "train":
            return split
    return resolved_splits[0]


def _resolve_non_yolov8_validation_split(
    resolved_splits: tuple[_ResolvedDetectionSplit, ...],
) -> _ResolvedDetectionSplit | None:
    """解析非 YOLOv8 暂存路径使用的验证 split。"""

    validation_names = {"val", "valid", "validation", "test"}
    for split in resolved_splits:
        if split.name.lower() in validation_names:
            return split
    return None


def _load_non_yolov8_training_samples(
    *,
    imports: _TrainingImports,
    split: _ResolvedDetectionSplit,
) -> tuple[tuple[_ResolvedTrainingSample, ...], tuple[str, ...], tuple[int, ...]]:
    """把非 YOLOv8 暂存路径 detection split 转成训练样本列表。"""

    del imports
    annotation_payload = split.annotation_payload
    categories_payload = annotation_payload.get("categories", [])
    images_payload = annotation_payload.get("images", [])
    annotations_payload = annotation_payload.get("annotations", [])
    if not isinstance(categories_payload, list) or not isinstance(images_payload, list):
        raise InvalidRequestError(
            "detection annotation 结构不合法",
            details={
                "split_name": split.name,
                "annotation_file": str(split.annotation_file) if split.annotation_file is not None else None,
            },
        )
    category_names: list[str] = []
    category_ids: list[int] = []
    category_id_to_index: dict[int, int] = {}
    for category_item in categories_payload:
        if not isinstance(category_item, dict):
            continue
        category_id = category_item.get("id")
        category_name = str(category_item.get("name") or "").strip()
        if not isinstance(category_id, int) or not category_name:
            continue
        category_id_to_index[category_id] = len(category_names)
        category_names.append(category_name)
        category_ids.append(category_id)
    if not category_names:
        raise InvalidRequestError("训练输入缺少有效的 categories")

    image_meta_by_id: dict[int, dict[str, object]] = {}
    for image_item in images_payload:
        if not isinstance(image_item, dict):
            continue
        image_id = image_item.get("id")
        file_name = str(image_item.get("file_name") or "").strip()
        width = image_item.get("width")
        height = image_item.get("height")
        if (
            not isinstance(image_id, int)
            or not file_name
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
        ):
            continue
        image_meta_by_id[image_id] = {
            "file_name": file_name,
            "width": width,
            "height": height,
            "annotations": [],
        }
    for annotation_item in annotations_payload if isinstance(annotations_payload, list) else ():
        if not isinstance(annotation_item, dict):
            continue
        image_id = annotation_item.get("image_id")
        category_id = annotation_item.get("category_id")
        bbox = annotation_item.get("bbox")
        image_meta = image_meta_by_id.get(image_id if isinstance(image_id, int) else -1)
        category_index = category_id_to_index.get(category_id if isinstance(category_id, int) else -1)
        if image_meta is None or category_index is None or not isinstance(bbox, list | tuple) or len(bbox) != 4:
            continue
        x, y, w, h = bbox
        if not all(isinstance(item, int | float) for item in (x, y, w, h)):
            continue
        if float(w) <= 0.0 or float(h) <= 0.0:
            continue
        width = int(image_meta["width"])
        height = int(image_meta["height"])
        x1 = max(0.0, min(float(x), float(width)))
        y1 = max(0.0, min(float(y), float(height)))
        x2 = max(0.0, min(float(x + w), float(width)))
        y2 = max(0.0, min(float(y + h), float(height)))
        if x2 <= x1 or y2 <= y1:
            continue
        image_meta["annotations"].append(
            _ResolvedTrainingAnnotation(
                category_index=category_index,
                category_id=int(category_id),
                bbox_xyxy=(x1, y1, x2, y2),
            )
        )

    resolved_samples: list[_ResolvedTrainingSample] = []
    for image_id, image_meta in image_meta_by_id.items():
        file_name = str(image_meta["file_name"])
        width = int(image_meta["width"])
        height = int(image_meta["height"])
        annotations = tuple(
            item
            for item in image_meta["annotations"]
            if isinstance(item, _ResolvedTrainingAnnotation)
        )
        image_path = split.image_root / file_name
        if not image_path.is_file():
            continue
        resolved_samples.append(
            _ResolvedTrainingSample(
                image_id=image_id,
                image_path=image_path,
                image_width=width,
                image_height=height,
                annotations=annotations,
            )
        )
    return tuple(resolved_samples), tuple(category_names), tuple(category_ids)


def _build_coco_annotation_payload_from_yolo_detection_split(
    *,
    imports: _TrainingImports,
    split_name: str,
    image_root: Path,
    label_root: Path,
    category_names: tuple[str, ...],
) -> dict[str, object]:
    """把 YOLO detection 标签目录转换成内存中的 COCO payload。"""

    images_payload: list[dict[str, object]] = []
    annotations_payload: list[dict[str, object]] = []
    categories_payload = [
        {
            "id": category_index + 1,
            "name": category_name,
        }
        for category_index, category_name in enumerate(category_names)
    ]
    annotation_id = 1
    for image_id, image_path in enumerate(_iter_image_files(image_root), start=1):
        image_height, image_width = _read_image_shape(imports=imports, image_path=image_path)
        relative_image_path = image_path.relative_to(image_root)
        images_payload.append(
            {
                "id": image_id,
                "file_name": relative_image_path.as_posix(),
                "width": image_width,
                "height": image_height,
            }
        )
        label_path = (label_root / relative_image_path).with_suffix(".txt")
        annotation_rows, annotation_id = _parse_yolo_detection_label_file(
            label_path=label_path,
            split_name=split_name,
            image_id=image_id,
            image_width=image_width,
            image_height=image_height,
            category_count=len(category_names),
            next_annotation_id=annotation_id,
        )
        annotations_payload.extend(annotation_rows)
    return {
        "images": images_payload,
        "annotations": annotations_payload,
        "categories": categories_payload,
    }


def _iter_image_files(image_root: Path) -> tuple[Path, ...]:
    """收集目录下全部训练图片。"""

    image_suffixes = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
    return tuple(
        sorted(
            (
                candidate
                for candidate in image_root.rglob("*")
                if candidate.is_file() and candidate.suffix.lower() in image_suffixes
            ),
            key=lambda item: item.as_posix().lower(),
        )
    )


def _read_image_shape(
    *,
    imports: _TrainingImports,
    image_path: Path,
) -> tuple[int, int]:
    """读取一张训练图片的尺寸。"""

    image = imports.cv2.imread(str(image_path), imports.cv2.IMREAD_UNCHANGED)
    if image is None:
        raise InvalidRequestError(
            "训练输入图片无法读取",
            details={"image_path": str(image_path)},
        )
    image_height = int(image.shape[0])
    image_width = int(image.shape[1])
    if image_height <= 0 or image_width <= 0:
        raise InvalidRequestError(
            "训练输入图片尺寸无效",
            details={"image_path": str(image_path)},
        )
    return image_height, image_width


def _parse_yolo_detection_label_file(
    *,
    label_path: Path,
    split_name: str,
    image_id: int,
    image_width: int,
    image_height: int,
    category_count: int,
    next_annotation_id: int,
) -> tuple[list[dict[str, object]], int]:
    """解析一个 YOLO detection label 文件。"""

    if not label_path.is_file():
        return [], next_annotation_id
    annotation_rows: list[dict[str, object]] = []
    annotation_id = next_annotation_id
    for line_index, raw_line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise InvalidRequestError(
                "YOLO detection 标注行必须是 5 列",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            )
        try:
            category_index = int(parts[0])
            x_center = float(parts[1])
            y_center = float(parts[2])
            box_width = float(parts[3])
            box_height = float(parts[4])
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO detection 标注行包含非法数字",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            ) from error
        if category_index < 0 or category_index >= category_count:
            raise InvalidRequestError(
                "YOLO detection 标注行类别索引越界",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                    "category_index": category_index,
                    "category_count": category_count,
                },
            )
        if box_width <= 0.0 or box_height <= 0.0:
            continue
        normalized_x1 = x_center - (box_width / 2.0)
        normalized_y1 = y_center - (box_height / 2.0)
        normalized_x2 = x_center + (box_width / 2.0)
        normalized_y2 = y_center + (box_height / 2.0)
        x1 = max(0.0, min(normalized_x1 * float(image_width), float(image_width)))
        y1 = max(0.0, min(normalized_y1 * float(image_height), float(image_height)))
        x2 = max(0.0, min(normalized_x2 * float(image_width), float(image_width)))
        y2 = max(0.0, min(normalized_y2 * float(image_height), float(image_height)))
        bbox_width = max(0.0, x2 - x1)
        bbox_height = max(0.0, y2 - y1)
        if bbox_width <= 0.0 or bbox_height <= 0.0:
            continue
        annotation_rows.append(
            {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": category_index + 1,
                "bbox": [x1, y1, bbox_width, bbox_height],
                "area": bbox_width * bbox_height,
                "iscrowd": 0,
            }
        )
        annotation_id += 1
    return annotation_rows, annotation_id


def _resolve_input_size(input_size: tuple[int, int] | None) -> tuple[int, int]:
    """解析训练输入尺寸。"""

    if input_size is None:
        return YOLO_PRIMARY_DEFAULT_INPUT_SIZE
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

    load_summary = load_yolo_primary_checkpoint(
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
    resume_epoch = int(raw_resume_epoch) if isinstance(raw_resume_epoch, int) and raw_resume_epoch >= 0 else 0
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
        epoch_history=_normalize_history_items(checkpoint_payload.get("metrics_history")),
        validation_history=_normalize_history_items(checkpoint_payload.get("validation_history")),
        evaluated_epochs=_normalize_evaluated_epochs(checkpoint_payload.get("evaluated_epochs")),
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
    if not isinstance(checkpoint_category_names, list) or len(checkpoint_category_names) != expected_num_classes:
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
        raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前训练请求不一致")


def _assert_resume_optional_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float | None,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的可选浮点配置与当前任务一致。"""

    if expected_value is None:
        if checkpoint_value is not None:
            raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前训练请求不一致")
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

    if not isinstance(checkpoint_value, int) or int(checkpoint_value) != int(expected_value):
        raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前训练请求不一致")


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


def _build_non_yolov8_training_batch(
    *,
    imports: _TrainingImports,
    samples: list[_ResolvedTrainingSample],
    input_size: tuple[int, int],
    device: str,
    runtime_precision: str,
    augment_training: bool = False,
    available_samples: tuple[_ResolvedTrainingSample, ...] | None = None,
    augmentation_options: _DetectionAugmentationOptions | None = None,
) -> tuple[Any, tuple[_PreparedTrainingTarget, ...]]:
    """把非 YOLOv8 暂存路径样本拼成训练 batch。"""

    np_module = imports.np
    torch = imports.torch
    image_tensors: list[Any] = []
    prepared_targets: list[_PreparedTrainingTarget] = []
    resolved_available_samples = (
        available_samples
        if available_samples is not None and len(available_samples) > 0
        else tuple(samples)
    )
    resolved_augmentation_options = (
        augmentation_options
        if augmentation_options is not None
        else _resolve_detection_augmentation_options({})
    )
    for sample in samples:
        if augment_training:
            prepared_image, resized_boxes, resized_categories = _prepare_augmented_detection_sample(
                imports=imports,
                primary_sample=sample,
                available_samples=resolved_available_samples,
                input_size=input_size,
                augmentation_options=resolved_augmentation_options,
            )
        else:
            prepared_image, resized_boxes, resized_categories = _prepare_detection_sample_without_augmentation(
                imports=imports,
                sample=sample,
                input_size=input_size,
            )
        rgb_image = imports.cv2.cvtColor(prepared_image, imports.cv2.COLOR_BGR2RGB)
        image_array = rgb_image.astype(np_module.float32) / 255.0
        image_array = np_module.transpose(image_array, (2, 0, 1))
        image_tensors.append(torch.from_numpy(image_array))
        prepared_targets.append(
            _PreparedTrainingTarget(
                image_id=sample.image_id,
                image_width=(input_size[1] if augment_training else sample.image_width),
                image_height=(input_size[0] if augment_training else sample.image_height),
                boxes_xyxy=tuple(resized_boxes),
                category_indexes=tuple(resized_categories),
            )
        )
    images = torch.stack(image_tensors, dim=0).to(device)
    if runtime_precision == "fp16":
        images = images.half()
    return images, tuple(prepared_targets)


def _prepare_detection_sample_without_augmentation(
    *,
    imports: _TrainingImports,
    sample: _ResolvedTrainingSample,
    input_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """按当前正式输入尺寸直接缩放单张 detection 训练样本。"""

    image = _load_training_image_array(imports=imports, sample=sample)
    return _resize_detection_sample_to_size(
        imports=imports,
        image=image,
        annotations=sample.annotations,
        output_size=input_size,
    )


def _prepare_augmented_detection_sample(
    *,
    imports: _TrainingImports,
    primary_sample: _ResolvedTrainingSample,
    available_samples: tuple[_ResolvedTrainingSample, ...],
    input_size: tuple[int, int],
    augmentation_options: _DetectionAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造启用增强后的 detection 训练样本。"""

    if (
        augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        image, boxes_xyxy, category_indexes = _build_mosaic_detection_sample(
            imports=imports,
            primary_sample=primary_sample,
            available_samples=available_samples,
            input_size=input_size,
            augmentation_options=augmentation_options,
        )
    else:
        image, boxes_xyxy, category_indexes = _prepare_detection_sample_without_augmentation(
            imports=imports,
            sample=primary_sample,
            input_size=input_size,
        )

    if (
        augmentation_options.enable_mixup
        and augmentation_options.mixup_prob > 0.0
        and random.random() < augmentation_options.mixup_prob
    ):
        mixup_source_sample = random.choice(available_samples)
        if (
            augmentation_options.mosaic_prob > 0.0
            and random.random() < augmentation_options.mosaic_prob
        ):
            mixup_image, mixup_boxes, mixup_categories = _build_mosaic_detection_sample(
                imports=imports,
                primary_sample=mixup_source_sample,
                available_samples=available_samples,
                input_size=input_size,
                augmentation_options=augmentation_options,
            )
        else:
            mixup_image, mixup_boxes, mixup_categories = _build_scaled_mixup_sample(
                imports=imports,
                sample=mixup_source_sample,
                input_size=input_size,
                scale_range=augmentation_options.mixup_scale,
            )
        image = _apply_mixup(
            np_module=imports.np,
            image=image,
            other_image=mixup_image,
        )
        boxes_xyxy.extend(mixup_boxes)
        category_indexes.extend(mixup_categories)

    image = _apply_random_hsv(
        imports=imports,
        image=image,
        hsv_prob=augmentation_options.hsv_prob,
    )
    image, boxes_xyxy = _apply_random_flip(
        image=image,
        boxes_xyxy=boxes_xyxy,
        flip_prob=augmentation_options.flip_prob,
        output_size=input_size,
    )
    image, boxes_xyxy = _apply_random_affine(
        imports=imports,
        image=image,
        boxes_xyxy=boxes_xyxy,
        output_size=input_size,
        degrees=augmentation_options.degrees,
        translate=augmentation_options.translate,
        shear=augmentation_options.shear,
    )
    filtered_boxes, filtered_categories = _filter_training_boxes(
        boxes_xyxy=boxes_xyxy,
        category_indexes=category_indexes,
        output_size=input_size,
    )
    return image, filtered_boxes, filtered_categories


def _build_mosaic_detection_sample(
    *,
    imports: _TrainingImports,
    primary_sample: _ResolvedTrainingSample,
    available_samples: tuple[_ResolvedTrainingSample, ...],
    input_size: tuple[int, int],
    augmentation_options: _DetectionAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造一张 2x2 Mosaic detection 样本。"""

    np_module = imports.np
    output_height, output_width = int(input_size[0]), int(input_size[1])
    top_height = output_height // 2
    left_width = output_width // 2
    placements = (
        (0, 0, top_height, left_width),
        (0, left_width, top_height, output_width - left_width),
        (top_height, 0, output_height - top_height, left_width),
        (top_height, left_width, output_height - top_height, output_width - left_width),
    )
    canvas = np_module.full((output_height, output_width, 3), 114, dtype=np_module.uint8)
    boxes_xyxy: list[tuple[float, float, float, float]] = []
    category_indexes: list[int] = []
    selected_samples = [primary_sample]
    if available_samples:
        selected_samples.extend(random.choice(available_samples) for _ in range(3))
    else:
        selected_samples.extend(primary_sample for _ in range(3))

    for sample, (top, left, cell_height, cell_width) in zip(
        selected_samples,
        placements,
        strict=True,
    ):
        scale_gain = random.uniform(
            augmentation_options.mosaic_scale[0],
            augmentation_options.mosaic_scale[1],
        )
        cell_image, cell_boxes, cell_categories = _build_scaled_cell_sample(
            imports=imports,
            sample=sample,
            output_size=(cell_height, cell_width),
            scale_gain=scale_gain,
        )
        canvas[top : top + cell_height, left : left + cell_width] = cell_image
        for box in cell_boxes:
            boxes_xyxy.append(
                (
                    float(box[0] + left),
                    float(box[1] + top),
                    float(box[2] + left),
                    float(box[3] + top),
                )
            )
        category_indexes.extend(cell_categories)
    return canvas, boxes_xyxy, category_indexes


def _build_scaled_mixup_sample(
    *,
    imports: _TrainingImports,
    sample: _ResolvedTrainingSample,
    input_size: tuple[int, int],
    scale_range: tuple[float, float],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造 MixUp 使用的缩放样本。"""

    scale_gain = random.uniform(scale_range[0], scale_range[1])
    return _build_scaled_cell_sample(
        imports=imports,
        sample=sample,
        output_size=input_size,
        scale_gain=scale_gain,
    )


def _build_scaled_cell_sample(
    *,
    imports: _TrainingImports,
    sample: _ResolvedTrainingSample,
    output_size: tuple[int, int],
    scale_gain: float,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """把样本按随机缩放后裁剪/填充到指定画布尺寸。"""

    np_module = imports.np
    image = _load_training_image_array(imports=imports, sample=sample)
    output_height, output_width = int(output_size[0]), int(output_size[1])
    source_height, source_width = int(image.shape[0]), int(image.shape[1])
    if source_height <= 0 or source_width <= 0:
        raise InvalidRequestError("训练样本图片尺寸不合法")
    base_scale = min(
        float(output_width) / max(1.0, float(source_width)),
        float(output_height) / max(1.0, float(source_height)),
    )
    resized_scale = max(1e-6, base_scale * max(0.01, float(scale_gain)))
    resized_width = max(1, int(round(source_width * resized_scale)))
    resized_height = max(1, int(round(source_height * resized_scale)))
    resized_image = imports.cv2.resize(
        image,
        (resized_width, resized_height),
        interpolation=imports.cv2.INTER_LINEAR,
    )
    canvas = np_module.full((output_height, output_width, 3), 114, dtype=np_module.uint8)

    if resized_width > output_width:
        source_x = random.randint(0, resized_width - output_width)
        target_x = 0
        copy_width = output_width
    else:
        source_x = 0
        target_x = random.randint(0, output_width - resized_width)
        copy_width = resized_width
    if resized_height > output_height:
        source_y = random.randint(0, resized_height - output_height)
        target_y = 0
        copy_height = output_height
    else:
        source_y = 0
        target_y = random.randint(0, output_height - resized_height)
        copy_height = resized_height
    canvas[
        target_y : target_y + copy_height,
        target_x : target_x + copy_width,
    ] = resized_image[
        source_y : source_y + copy_height,
        source_x : source_x + copy_width,
    ]

    boxes_xyxy: list[tuple[float, float, float, float]] = []
    category_indexes: list[int] = []
    for annotation in sample.annotations:
        scaled_x1 = float(annotation.bbox_xyxy[0]) * resized_scale - float(source_x) + float(target_x)
        scaled_y1 = float(annotation.bbox_xyxy[1]) * resized_scale - float(source_y) + float(target_y)
        scaled_x2 = float(annotation.bbox_xyxy[2]) * resized_scale - float(source_x) + float(target_x)
        scaled_y2 = float(annotation.bbox_xyxy[3]) * resized_scale - float(source_y) + float(target_y)
        clipped_box = _clip_box_xyxy(
            box_xyxy=(scaled_x1, scaled_y1, scaled_x2, scaled_y2),
            output_size=output_size,
        )
        if clipped_box is None:
            continue
        boxes_xyxy.append(clipped_box)
        category_indexes.append(annotation.category_index)
    return canvas, boxes_xyxy, category_indexes


def _resize_detection_sample_to_size(
    *,
    imports: _TrainingImports,
    image: Any,
    annotations: tuple[_ResolvedTrainingAnnotation, ...],
    output_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """把单张样本直接缩放到目标尺寸。"""

    output_height, output_width = int(output_size[0]), int(output_size[1])
    resized = imports.cv2.resize(
        image,
        (output_width, output_height),
        interpolation=imports.cv2.INTER_LINEAR,
    )
    scale_x = float(output_width) / max(1.0, float(image.shape[1]))
    scale_y = float(output_height) / max(1.0, float(image.shape[0]))
    boxes_xyxy: list[tuple[float, float, float, float]] = []
    category_indexes: list[int] = []
    for annotation in annotations:
        clipped_box = _clip_box_xyxy(
            box_xyxy=(
                float(annotation.bbox_xyxy[0]) * scale_x,
                float(annotation.bbox_xyxy[1]) * scale_y,
                float(annotation.bbox_xyxy[2]) * scale_x,
                float(annotation.bbox_xyxy[3]) * scale_y,
            ),
            output_size=output_size,
        )
        if clipped_box is None:
            continue
        boxes_xyxy.append(clipped_box)
        category_indexes.append(annotation.category_index)
    return resized, boxes_xyxy, category_indexes


def _load_training_image_array(
    *,
    imports: _TrainingImports,
    sample: _ResolvedTrainingSample,
) -> Any:
    """读取单张训练样本图片。"""

    image = imports.cv2.imread(str(sample.image_path), imports.cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidRequestError(
            "训练样本图片无法读取",
            details={"image_path": str(sample.image_path)},
        )
    return image


def _apply_mixup(
    *,
    np_module: Any,
    image: Any,
    other_image: Any,
) -> Any:
    """把两张同尺寸图片按固定权重混合。"""

    mixed = (
        image.astype(np_module.float32) * 0.5
        + other_image.astype(np_module.float32) * 0.5
    )
    return mixed.clip(0.0, 255.0).astype(np_module.uint8)


def _apply_random_hsv(
    *,
    imports: _TrainingImports,
    image: Any,
    hsv_prob: float,
) -> Any:
    """按概率执行随机 HSV 抖动。"""

    if hsv_prob <= 0.0 or random.random() >= hsv_prob:
        return image
    hsv_image = imports.cv2.cvtColor(image, imports.cv2.COLOR_BGR2HSV).astype(
        imports.np.float32
    )
    hue_gain = 1.0 + random.uniform(-0.015, 0.015)
    saturation_gain = 1.0 + random.uniform(-0.7, 0.7)
    value_gain = 1.0 + random.uniform(-0.4, 0.4)
    hsv_image[..., 0] = (hsv_image[..., 0] * hue_gain) % 180.0
    hsv_image[..., 1] = imports.np.clip(hsv_image[..., 1] * saturation_gain, 0.0, 255.0)
    hsv_image[..., 2] = imports.np.clip(hsv_image[..., 2] * value_gain, 0.0, 255.0)
    return imports.cv2.cvtColor(
        hsv_image.astype(imports.np.uint8),
        imports.cv2.COLOR_HSV2BGR,
    )


def _apply_random_flip(
    *,
    image: Any,
    boxes_xyxy: list[tuple[float, float, float, float]],
    flip_prob: float,
    output_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]]]:
    """按概率执行随机水平翻转。"""

    if flip_prob <= 0.0 or random.random() >= flip_prob:
        return image, boxes_xyxy
    output_width = float(output_size[1])
    flipped_image = image[:, ::-1].copy()
    flipped_boxes: list[tuple[float, float, float, float]] = []
    for x1, y1, x2, y2 in boxes_xyxy:
        flipped_boxes.append((output_width - x2, y1, output_width - x1, y2))
    return flipped_image, flipped_boxes


def _apply_random_affine(
    *,
    imports: _TrainingImports,
    image: Any,
    boxes_xyxy: list[tuple[float, float, float, float]],
    output_size: tuple[int, int],
    degrees: float,
    translate: float,
    shear: float,
) -> tuple[Any, list[tuple[float, float, float, float]]]:
    """执行随机仿射增强，并同步变换 bbox。"""

    if degrees <= 0.0 and translate <= 0.0 and shear <= 0.0:
        return image, boxes_xyxy
    output_height, output_width = int(output_size[0]), int(output_size[1])
    center = (float(output_width) / 2.0, float(output_height) / 2.0)
    rotation_matrix = imports.cv2.getRotationMatrix2D(
        center,
        random.uniform(-degrees, degrees) if degrees > 0.0 else 0.0,
        1.0,
    )
    affine_matrix = imports.np.eye(3, dtype=imports.np.float32)
    affine_matrix[:2, :] = rotation_matrix
    shear_x = math.tan(math.radians(random.uniform(-shear, shear))) if shear > 0.0 else 0.0
    shear_y = math.tan(math.radians(random.uniform(-shear, shear))) if shear > 0.0 else 0.0
    shear_matrix = imports.np.array(
        [[1.0, shear_x, 0.0], [shear_y, 1.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=imports.np.float32,
    )
    translate_x = random.uniform(-translate, translate) * float(output_width) if translate > 0.0 else 0.0
    translate_y = random.uniform(-translate, translate) * float(output_height) if translate > 0.0 else 0.0
    translate_matrix = imports.np.array(
        [[1.0, 0.0, translate_x], [0.0, 1.0, translate_y], [0.0, 0.0, 1.0]],
        dtype=imports.np.float32,
    )
    composed_matrix = translate_matrix @ shear_matrix @ affine_matrix
    warped_image = imports.cv2.warpAffine(
        image,
        composed_matrix[:2],
        (output_width, output_height),
        flags=imports.cv2.INTER_LINEAR,
        borderValue=(114, 114, 114),
    )
    if not boxes_xyxy:
        return warped_image, boxes_xyxy

    transformed_boxes: list[tuple[float, float, float, float]] = []
    for box_xyxy in boxes_xyxy:
        corners = imports.np.array(
            [
                [box_xyxy[0], box_xyxy[1], 1.0],
                [box_xyxy[2], box_xyxy[1], 1.0],
                [box_xyxy[2], box_xyxy[3], 1.0],
                [box_xyxy[0], box_xyxy[3], 1.0],
            ],
            dtype=imports.np.float32,
        )
        transformed_corners = corners @ composed_matrix.T
        clipped_box = _clip_box_xyxy(
            box_xyxy=(
                float(transformed_corners[:, 0].min()),
                float(transformed_corners[:, 1].min()),
                float(transformed_corners[:, 0].max()),
                float(transformed_corners[:, 1].max()),
            ),
            output_size=output_size,
        )
        if clipped_box is not None:
            transformed_boxes.append(clipped_box)
    return warped_image, transformed_boxes


def _filter_training_boxes(
    *,
    boxes_xyxy: list[tuple[float, float, float, float]],
    category_indexes: list[int],
    output_size: tuple[int, int],
) -> tuple[list[tuple[float, float, float, float]], list[int]]:
    """过滤增强后退化或越界的训练框。"""

    filtered_boxes: list[tuple[float, float, float, float]] = []
    filtered_categories: list[int] = []
    for box_xyxy, category_index in zip(boxes_xyxy, category_indexes, strict=False):
        clipped_box = _clip_box_xyxy(box_xyxy=box_xyxy, output_size=output_size)
        if clipped_box is None:
            continue
        filtered_boxes.append(clipped_box)
        filtered_categories.append(int(category_index))
    return filtered_boxes, filtered_categories


def _clip_box_xyxy(
    *,
    box_xyxy: tuple[float, float, float, float],
    output_size: tuple[int, int],
) -> tuple[float, float, float, float] | None:
    """把 bbox 裁剪到图像范围内。"""

    output_height, output_width = float(output_size[0]), float(output_size[1])
    x1 = max(0.0, min(float(box_xyxy[0]), output_width))
    y1 = max(0.0, min(float(box_xyxy[1]), output_height))
    x2 = max(0.0, min(float(box_xyxy[2]), output_width))
    y2 = max(0.0, min(float(box_xyxy[3]), output_height))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _unwrap_detection_outputs(outputs: Any) -> dict[str, Any]:
    """把 detection 训练输出规整成 one2many 结果。"""

    if isinstance(outputs, dict) and "boxes" in outputs and "scores" in outputs:
        return outputs
    if isinstance(outputs, dict) and "one2many" in outputs:
        one2many = outputs.get("one2many")
        if isinstance(one2many, dict) and "boxes" in one2many and "scores" in one2many:
            return one2many
    raise ServiceConfigurationError("当前 YOLO detection 训练输出结构不合法")


def _unwrap_e2e_detection_outputs(outputs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """把端到端检测训练输出拆分为 one2many 和 one2one 两个分支。

    Returns:
        (one2many_outputs, one2one_outputs): 两个分支的原始输出字典。
    """

    if not isinstance(outputs, dict):
        raise ServiceConfigurationError("端到端训练输出必须是字典")
    one2many = outputs.get("one2many")
    one2one = outputs.get("one2one")
    if not isinstance(one2many, dict) or "boxes" not in one2many or "scores" not in one2many:
        raise ServiceConfigurationError("端到端训练输出缺少有效的 one2many 分支")
    if not isinstance(one2one, dict) or "boxes" not in one2one or "scores" not in one2one:
        raise ServiceConfigurationError("端到端训练输出缺少有效的 one2one 分支")
    return one2many, one2one


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
    """按真实检测目标计算分类、框回归和 DFL 损失。

    Args:
        assign_topk2: 可选的二次精选参数，用于 E2E 训练的 one2one 分支。
    """

    torch = imports.torch
    detect_head = model.model[-1]
    if is_yolov8_detection_core_model(model):
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

    prediction_bundle = decode_detection_training_predictions(
        torch_module=torch,
        detect_head=detect_head,
        raw_outputs=raw_outputs,
    )
    class_logits = prediction_bundle["class_logits"]
    class_probabilities = class_logits.sigmoid()
    pred_boxes = prediction_bundle["boxes_xyxy"]
    distance_logits = prediction_bundle["distance_logits"]
    anchor_points = prediction_bundle["anchor_points"]
    stride_tensor = prediction_bundle["stride_tensor"]
    anchor_centers_xy = prediction_bundle["anchor_centers_xy"]
    reg_max = int(prediction_bundle["reg_max"])

    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_foreground = 0
    total_target_score = class_logits.new_zeros(())

    for batch_index, target in enumerate(batch_targets):
        image_class_logits = class_logits[batch_index]
        image_class_probabilities = class_probabilities[batch_index]
        image_pred_boxes = pred_boxes[batch_index]
        target_scores = torch.zeros_like(image_class_logits)

        if target.boxes_xyxy:
            gt_boxes = torch.tensor(
                target.boxes_xyxy,
                device=image_pred_boxes.device,
                dtype=image_pred_boxes.dtype,
            )
            gt_classes = torch.tensor(
                target.category_indexes,
                device=image_pred_boxes.device,
                dtype=torch.long,
            )
            # 目标分配只决定标签，不参与反向传播；内部会做 top-k 与 mask 写入。
            # 如果让它挂在 autograd 图上，E2E 双分支训练会因为 in-place 更新触发 backward 版本冲突。
            with torch.no_grad():
                assignment = assign_detection_targets(
                    torch_module=torch,
                    pred_boxes=image_pred_boxes.detach(),
                    class_probabilities=image_class_probabilities.detach(),
                    anchor_centers_xy=anchor_centers_xy,
                    gt_boxes=gt_boxes,
                    gt_classes=gt_classes,
                    topk=assign_topk,
                    alpha=assign_alpha,
                    beta=assign_beta,
                    topk2=assign_topk2,
                )
            if int(assignment["foreground_mask"].sum().item()) > 0:
                foreground_mask = assignment["foreground_mask"]
                assigned_gt_indices = assignment["assigned_gt_indices"][foreground_mask]
                quality_scores = assignment["quality_scores"][foreground_mask]
                target_scores[foreground_mask, gt_classes[assigned_gt_indices]] = quality_scores

                foreground_pred_boxes = image_pred_boxes[foreground_mask]
                foreground_gt_boxes = gt_boxes[assigned_gt_indices]
                iou_values = box_iou_aligned(
                    torch_module=torch,
                    boxes1=foreground_pred_boxes,
                    boxes2=foreground_gt_boxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + (1.0 - iou_values).sum()
                total_foreground += int(foreground_mask.sum().item())
                total_target_score = total_target_score + quality_scores.sum()

                foreground_anchor_points = anchor_points[foreground_mask]
                foreground_stride_tensor = stride_tensor[foreground_mask]
                target_distances = bbox_xyxy_to_distances(
                    torch_module=torch,
                    boxes_xyxy=foreground_gt_boxes,
                    anchor_points=foreground_anchor_points,
                    stride_tensor=foreground_stride_tensor,
                    reg_max=reg_max,
                )
                if reg_max > 1:
                    foreground_distance_logits = distance_logits[batch_index][foreground_mask].view(-1, 4, reg_max)
                    total_dfl_loss = total_dfl_loss + distribution_focal_loss(
                        torch_module=torch,
                        logits=foreground_distance_logits,
                        target=target_distances,
                    ).sum()
                else:
                    foreground_distance_logits = distance_logits[batch_index][foreground_mask].view(-1, 4)
                    total_dfl_loss = total_dfl_loss + torch.nn.functional.smooth_l1_loss(
                        torch.nn.functional.softplus(foreground_distance_logits),
                        target_distances,
                        reduction="sum",
                    )

        total_class_loss = total_class_loss + torch.nn.functional.binary_cross_entropy_with_logits(
            image_class_logits,
            target_scores,
            reduction="sum",
        )

    normalizer = total_target_score.clamp_min(1.0)
    class_loss = total_class_loss / normalizer
    foreground_normalizer = max(total_foreground, 1)
    box_loss = total_box_loss / foreground_normalizer
    dfl_loss = total_dfl_loss / foreground_normalizer
    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
    )
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
    }


def _compute_e2e_detection_loss(
    *,
    imports: _TrainingImports,
    model: Any,
    raw_outputs: tuple[dict[str, Any], dict[str, Any]],
    batch_targets: tuple[_PreparedTrainingTarget, ...],
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    e2e_o2m_weight: float,
    e2e_o2o_weight: float,
    e2e_o2o_topk: int = 7,
    e2e_o2o_topk2: int = 1,
) -> dict[str, Any]:
    """计算端到端检测训练的双分支加权损失。

    E2E 训练同时优化两个分支：
    - one2many: 使用标准 TAL (topk=10) 分配，提供丰富的梯度信号
    - one2one: 使用精选 TAL (topk=7, topk2=1) 分配，生成高质量一对一标签用于推理

    损失通过可学习的权重调度器加权求和：
    total_loss = o2m_weight * one2many_loss + o2o_weight * one2one_loss

    权重在训练过程中动态调整：
    - 初期: o2m_weight=0.8, o2o_weight=0.2 (one2many 主导，提供充足梯度)
    - 末期: o2m_weight=0.1, o2o_weight=0.9 (one2one 主导，确保推理精度)
    """
    one2many_outputs, one2one_outputs = raw_outputs

    # 计算 one2many 分支损失（标准 TAL，topk=10）
    one2many_loss_components = _compute_detection_loss(
        imports=imports,
        model=model,
        raw_outputs=one2many_outputs,
        batch_targets=batch_targets,
        num_classes=num_classes,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
    )

    # 计算 one2one 分支损失（精选 TAL，topk=7, topk2=1）
    one2one_loss_components = _compute_detection_loss(
        imports=imports,
        model=model,
        raw_outputs=one2one_outputs,
        batch_targets=batch_targets,
        num_classes=num_classes,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=e2e_o2o_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
        assign_topk2=e2e_o2o_topk2,
    )

    # 加权求和
    total_loss = (
        e2e_o2m_weight * one2many_loss_components["loss"]
        + e2e_o2o_weight * one2one_loss_components["loss"]
    )

    # 返回组合损失和两个分支的详细指标
    return {
        "loss": total_loss,
        "class_loss": one2one_loss_components["class_loss"],  # 日志只记录 one2one
        "box_loss": one2one_loss_components["box_loss"],
        "dfl_loss": one2one_loss_components["dfl_loss"],
        "one2many_loss": one2many_loss_components["loss"],
        "one2one_loss": one2one_loss_components["loss"],
        "e2e_o2m_weight": e2e_o2m_weight,
        "e2e_o2o_weight": e2e_o2o_weight,
    }


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
    use_yolov8_core_data: bool = False,
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
        use_yolov8_core_data=use_yolov8_core_data,
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
    is_end2end = bool(getattr(model, "end2end", False))
    if is_yolov8_detection_core_model(model) and not is_end2end:
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

    previous_training_mode = bool(model.training)
    model.train()
    batch_norm_states = _freeze_batch_norm_modules(imports=imports, model=model)
    epoch_totals = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
    if is_end2end:
        epoch_totals["one2many_loss"] = 0.0
        epoch_totals["one2one_loss"] = 0.0
    batch_count = 0
    try:
        with torch.no_grad():
            for batch_samples in _iter_batches(list(samples), batch_size):
                images, batch_targets = _build_non_yolov8_training_batch(
                    imports=imports,
                    samples=batch_samples,
                    input_size=input_size,
                    device=device,
                    runtime_precision=runtime_precision,
                    augment_training=False,
                )
                with autocast_context():
                    model_outputs = model(images)
                    if is_end2end:
                        loss_components = _compute_e2e_detection_loss(
                            imports=imports,
                            model=model,
                            raw_outputs=_unwrap_e2e_detection_outputs(model_outputs),
                            batch_targets=batch_targets,
                            num_classes=num_classes,
                            class_loss_weight=class_loss_weight,
                            box_loss_weight=box_loss_weight,
                            dfl_loss_weight=dfl_loss_weight,
                            assign_topk=assign_topk,
                            assign_alpha=assign_alpha,
                            assign_beta=assign_beta,
                            e2e_o2m_weight=0.1,
                            e2e_o2o_weight=0.9,
                        )
                    else:
                        raw_outputs = _unwrap_detection_outputs(model_outputs)
                        loss_components = _compute_detection_loss(
                            imports=imports,
                            model=model,
                            raw_outputs=raw_outputs,
                            batch_targets=batch_targets,
                            num_classes=num_classes,
                            class_loss_weight=class_loss_weight,
                            box_loss_weight=box_loss_weight,
                            dfl_loss_weight=dfl_loss_weight,
                            assign_topk=assign_topk,
                            assign_alpha=assign_alpha,
                            assign_beta=assign_beta,
                        )
                batch_count += 1
                for metric_name in epoch_totals:
                    epoch_totals[metric_name] += float(loss_components[metric_name].detach().item())
    finally:
        _restore_batch_norm_modules(batch_norm_states)
        model.train(previous_training_mode)
    if batch_count <= 0:
        return {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
    return {
        metric_name: round(metric_total / batch_count, 6)
        for metric_name, metric_total in epoch_totals.items()
    }


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
    use_yolov8_core_data: bool = False,
) -> dict[str, float]:
    """执行一次真实 COCO mAP 评估。"""

    if not samples or annotation_payload is None:
        return {"map50": 0.0, "map50_95": 0.0}
    if imports.COCO is None or imports.COCOeval is None:
        raise ServiceConfigurationError("当前环境缺少 pycocotools，无法执行 detection mAP 验证")

    torch = imports.torch
    previous_training_mode = bool(model.training)
    model.eval()
    detections: list[dict[str, object]] = []
    evaluation_postprocess_mode = (
        DETECTION_POSTPROCESS_MODE_END2END_TOPK
        if bool(getattr(model, "end2end", False))
        else DETECTION_POSTPROCESS_MODE_NMS
    )
    evaluation_max_detections = (
        DEFAULT_END2END_MAX_DETECTIONS
        if evaluation_postprocess_mode == DETECTION_POSTPROCESS_MODE_END2END_TOPK
        else None
    )
    try:
        with torch.no_grad():
            for batch_samples in _iter_batches(list(samples), batch_size):
                if use_yolov8_core_data:
                    images, batch_targets = build_yolov8_detection_training_batch(
                        imports=imports,
                        samples=batch_samples,
                        input_size=input_size,
                        device=device,
                        runtime_precision=runtime_precision,
                        augment_training=False,
                    )
                else:
                    images, batch_targets = _build_non_yolov8_training_batch(
                        imports=imports,
                        samples=batch_samples,
                        input_size=input_size,
                        device=device,
                        runtime_precision=runtime_precision,
                        augment_training=False,
                    )
                prediction_tensor = model(images)
                detections.extend(
                    _convert_primary_predictions_to_coco_detections(
                        imports=imports,
                        prediction_tensor=prediction_tensor,
                        batch_targets=batch_targets,
                        input_size=input_size,
                        category_ids=category_ids,
                        confidence_threshold=confidence_threshold,
                        nms_threshold=nms_threshold,
                        postprocess_mode=evaluation_postprocess_mode,
                        max_detections=evaluation_max_detections,
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


def _convert_primary_predictions_to_coco_detections(
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
            if width <= 0 or height <= 0 or resolved_class_id < 0 or resolved_class_id >= len(category_ids):
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


def _restore_batch_norm_modules(batch_norm_states: tuple[tuple[Any, bool], ...]) -> None:
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
            normalized_items.append({str(key): current_value for key, current_value in item.items()})
    return normalized_items


def _normalize_evaluated_epochs(value: object) -> tuple[int, ...]:
    """把 checkpoint 中的验证 epoch 列表归一成整数元组。"""

    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and item > 0)


def _move_optimizer_state_to_device(*, optimizer: Any, device: str) -> None:
    """把 optimizer 状态里的张量迁移到当前训练设备。"""

    for state in optimizer.state.values():
        if not isinstance(state, dict):
            continue
        for key, value in tuple(state.items()):
            if hasattr(value, "to"):
                state[key] = value.to(device=device)


def _build_checkpoint_state(
    *,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    model_type: str,
    model_scale: str,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    batch_size: int,
    max_epochs: int,
    epoch: int,
    precision: str,
    validation_split_name: str | None,
    evaluation_interval: int | None,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
    learning_rate: float,
    weight_decay: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    min_lr_ratio: float,
    grad_clip_norm: float,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: tuple[int, ...],
    warm_start_summary: dict[str, object],
    implementation_mode: str,
    augmentation_options: dict[str, object] | None,
    best_metric_name: str,
    best_metric_value: float | None,
    best_checkpoint_state: dict[str, object] | None,
) -> dict[str, object]:
    """构建一个可直接序列化保存的项目内训练 checkpoint 状态。"""

    if model_type == "yolov8":
        return build_yolov8_detection_checkpoint_state(
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            model_type=model_type,
            model_scale=model_scale,
            category_names=category_names,
            input_size=input_size,
            batch_size=batch_size,
            max_epochs=max_epochs,
            epoch=epoch,
            precision=precision,
            validation_split_name=validation_split_name,
            evaluation_interval=evaluation_interval,
            evaluation_confidence_threshold=evaluation_confidence_threshold,
            evaluation_nms_threshold=evaluation_nms_threshold,
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
            evaluated_epochs=evaluated_epochs,
            warm_start_summary=warm_start_summary,
            implementation_mode=implementation_mode,
            augmentation_options=augmentation_options,
            best_metric_name=best_metric_name,
            best_metric_value=best_metric_value,
            best_checkpoint_state=best_checkpoint_state,
        )

    return {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "scaler_state_dict": scaler.state_dict(),
        "model_type": model_type,
        "model_scale": model_scale,
        "category_names": list(category_names),
        "input_size": list(input_size),
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "epoch": epoch,
        "precision": precision,
        "validation_split_name": validation_split_name,
        "evaluation_interval": evaluation_interval,
        "evaluation_confidence_threshold": evaluation_confidence_threshold,
        "evaluation_nms_threshold": evaluation_nms_threshold,
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "class_loss_weight": class_loss_weight,
        "box_loss_weight": box_loss_weight,
        "dfl_loss_weight": dfl_loss_weight,
        "assign_topk": assign_topk,
        "assign_alpha": assign_alpha,
        "assign_beta": assign_beta,
        "min_lr_ratio": min_lr_ratio,
        "grad_clip_norm": grad_clip_norm,
        "metrics_history": metrics_history,
        "validation_history": validation_history,
        "evaluated_epochs": list(evaluated_epochs),
        "warm_start": warm_start_summary,
        "implementation_mode": implementation_mode,
        "augmentation": dict(augmentation_options or {}),
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "best_checkpoint_state": best_checkpoint_state,
    }


def _build_checkpoint_bytes(
    *,
    imports: _TrainingImports,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    model_type: str,
    model_scale: str,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    batch_size: int,
    max_epochs: int,
    epoch: int,
    precision: str,
    validation_split_name: str | None,
    evaluation_interval: int | None,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
    learning_rate: float,
    weight_decay: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    min_lr_ratio: float,
    grad_clip_norm: float,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: tuple[int, ...],
    warm_start_summary: dict[str, object],
    implementation_mode: str,
    augmentation_options: dict[str, object] | None,
    best_metric_name: str,
    best_metric_value: float | None,
    best_checkpoint_state: dict[str, object] | None,
) -> bytes:
    """把当前训练状态导出为项目内 checkpoint。"""

    checkpoint_state = _build_checkpoint_state(
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        model_type=model_type,
        model_scale=model_scale,
        category_names=category_names,
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        epoch=epoch,
        precision=precision,
        validation_split_name=validation_split_name,
        evaluation_interval=evaluation_interval,
        evaluation_confidence_threshold=evaluation_confidence_threshold,
        evaluation_nms_threshold=evaluation_nms_threshold,
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
        evaluated_epochs=evaluated_epochs,
        warm_start_summary=warm_start_summary,
        implementation_mode=implementation_mode,
        augmentation_options=augmentation_options,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=best_checkpoint_state,
    )
    if model_type == "yolov8":
        return encode_yolov8_detection_checkpoint_state(
            torch_module=imports.torch,
            checkpoint_state=checkpoint_state,
        )
    buffer = io.BytesIO()
    imports.torch.save(checkpoint_state, buffer)
    return buffer.getvalue()


def _build_checkpoint_bytes_from_state(
    *,
    imports: _TrainingImports,
    checkpoint_state: dict[str, object] | None,
) -> bytes:
    """把已缓存的 checkpoint 状态重新编码成二进制。"""

    if isinstance(checkpoint_state, dict) and checkpoint_state.get("model_type") == "yolov8":
        return encode_yolov8_detection_checkpoint_state(
            torch_module=imports.torch,
            checkpoint_state=checkpoint_state,
        )
    if checkpoint_state is None:
        return b""
    buffer = io.BytesIO()
    imports.torch.save(checkpoint_state, buffer)
    return buffer.getvalue()


def _load_checkpoint_state_from_bytes(
    *,
    imports: _TrainingImports,
    checkpoint_bytes: bytes,
) -> dict[str, object]:
    """从 checkpoint 二进制反序列化为字典状态。"""

    payload = imports.torch.load(io.BytesIO(checkpoint_bytes), map_location="cpu")
    if not isinstance(payload, dict):
        raise InvalidRequestError("checkpoint 内容不合法")
    return dict(payload)


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

    return _DetectionAugmentationOptions(
        flip_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "flip_prob",
                default=YOLO_PRIMARY_DEFAULT_FLIP_PROB,
            )
        ),
        hsv_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "hsv_prob",
                default=YOLO_PRIMARY_DEFAULT_HSV_PROB,
            )
        ),
        mosaic_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "mosaic_prob",
                default=YOLO_PRIMARY_DEFAULT_MOSAIC_PROB,
            )
        ),
        mixup_prob=_clamp_probability(
            _read_float_option(
                extra_options,
                "mixup_prob",
                default=YOLO_PRIMARY_DEFAULT_MIXUP_PROB,
            )
        ),
        enable_mixup=_read_bool_option(
            extra_options,
            "enable_mixup",
            default=YOLO_PRIMARY_DEFAULT_ENABLE_MIXUP,
        ),
        degrees=max(
            0.0,
            _read_float_option(
                extra_options,
                "degrees",
                default=YOLO_PRIMARY_DEFAULT_AFFINE_DEGREES,
            ),
        ),
        translate=max(
            0.0,
            _read_float_option(
                extra_options,
                "translate",
                default=YOLO_PRIMARY_DEFAULT_AFFINE_TRANSLATE,
            ),
        ),
        shear=max(
            0.0,
            _read_float_option(
                extra_options,
                "shear",
                default=YOLO_PRIMARY_DEFAULT_AFFINE_SHEAR,
            ),
        ),
        mosaic_scale=_read_float_pair_option(
            extra_options,
            "mosaic_scale",
            default=YOLO_PRIMARY_DEFAULT_MOSAIC_SCALE,
        ),
        mixup_scale=_read_float_pair_option(
            extra_options,
            "mixup_scale",
            default=YOLO_PRIMARY_DEFAULT_MIXUP_SCALE,
        ),
    )


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
        "degrees": options.degrees,
        "translate": options.translate,
        "shear": options.shear,
        "mosaic_scale": list(options.mosaic_scale),
        "mixup_scale": list(options.mixup_scale),
    }


def _clamp_probability(value: float) -> float:
    """把概率值裁剪到 [0, 1]。"""

    return max(0.0, min(1.0, float(value)))
