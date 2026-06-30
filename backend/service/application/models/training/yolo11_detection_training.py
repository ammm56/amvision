"""YOLO11 detection 训练执行入口。"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.training.yolo_detection_training_control import (
    YoloDetectionTrainingBatchProgress,
    YoloDetectionTrainingControlCommand,
    YoloDetectionTrainingEpochProgress,
    YoloDetectionTrainingPausedError,
    YoloDetectionTrainingSavePoint,
    YoloDetectionTrainingTerminatedError,
)
from backend.service.application.models.training.yolo_detection_training_execution import (
    YoloDetectionTrainingExecutionRequest,
    YoloDetectionTrainingExecutionResult,
)
from backend.service.application.models.yolo11_core.model import build_yolo11_model
from backend.service.application.models.yolo11_core.data import (
    build_yolo11_detection_training_batch,
    build_yolo11_task_augmentation_options,
    resolve_yolo11_task_augmentation_for_epoch,
    resolve_yolo11_task_batch_input_size,
    serialize_yolo11_detection_augmentation_options,
)
from backend.service.application.models.yolo11_core.training import (
    Yolo11DetectionTrainerEpochProgress,
    Yolo11DetectionResumeValidationRequest,
    Yolo11DetectionTrainingBatchProgress,
    Yolo11DetectionTrainingPausedError,
    Yolo11DetectionTrainingTerminatedError,
    build_yolo11_autocast_context,
    build_yolo11_detection_training_runtime,
    compute_yolo11_detection_training_loss,
    encode_yolo11_detection_checkpoint_state,
    evaluate_yolo11_detection_validation_losses,
    move_yolo11_optimizer_state_to_device,
    plan_yolo11_detection_training_execution,
    prepare_yolo11_detection_training_data_context,
    resolve_yolo11_detection_epoch_control,
    run_yolo11_detection_training_loop,
    validate_yolo11_detection_resume_checkpoint,
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
    YOLO11_DETECTION_DEFAULT_MAX_EPOCHS,
    YOLO11_DETECTION_DEFAULT_MIN_LR_RATIO,
    read_yolo11_float_option,
    read_yolo11_int_option,
    require_yolo11_detection_training_imports,
    resolve_yolo11_detection_input_size,
    resolve_yolo11_detection_runtime,
    unwrap_yolo11_detection_outputs,
)
from backend.service.application.models.yolo11_core.weights import (
    load_yolo11_checkpoint_file,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloModelEMA,
    YoloUltralyticsTrainingSchedule,
)
from backend.service.application.models.yolo11_core.training.execution import (
    YOLO11_DETECTION_CORE_IMPLEMENTATION_MODE,
)
from backend.service.application.models.yolo11_core.evaluation.detection import (
    convert_yolo11_predictions_to_coco_detections,
)
from backend.service.application.models.yolo11_core.postprocess.detection import (
    YOLO11_DETECTION_POSTPROCESS_MODE_NMS,
)


YOLO11_IMPLEMENTATION_MODE = YOLO11_DETECTION_CORE_IMPLEMENTATION_MODE
Yolo11DetectionTrainingExecutionRequest = YoloDetectionTrainingExecutionRequest
Yolo11DetectionTrainingExecutionResult = YoloDetectionTrainingExecutionResult
Yolo11TrainingBatchProgress = YoloDetectionTrainingBatchProgress
Yolo11TrainingEpochProgress = YoloDetectionTrainingEpochProgress


@dataclass(frozen=True)
class _Yolo11LoadedResumeState:
    """描述 YOLO11 detection resume checkpoint 解析后的训练状态。"""

    resume_epoch: int
    epoch_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    evaluated_epochs: tuple[int, ...]
    best_metric_name: str
    best_metric_value: float | None
    best_checkpoint_state: dict[str, object] | None
    ema_state_dict: dict[str, object] | None
    ema_updates: int
    warm_start_summary: dict[str, object]


def run_yolo11_detection_training(
    request: Yolo11DetectionTrainingExecutionRequest,
) -> Yolo11DetectionTrainingExecutionResult:
    """执行 YOLO11 detection 训练。"""

    _require_yolo11_detection_request(request)
    imports = require_yolo11_detection_training_imports()
    manifest_payload = dict(request.manifest_payload)
    data_context = prepare_yolo11_detection_training_data_context(
        dataset_storage=request.dataset_storage,
        cv2_module=imports.cv2,
        manifest_payload=manifest_payload,
    )
    resolved_splits = data_context.resolved_splits
    train_split = data_context.train_split
    validation_split = data_context.validation_split
    train_samples = data_context.train_samples
    category_names = data_context.category_names
    category_ids = data_context.category_ids
    validation_samples = data_context.validation_samples

    input_size = resolve_yolo11_detection_input_size(request.input_size)
    batch_size = max(1, int(request.batch_size or YOLO11_DETECTION_DEFAULT_BATCH_SIZE))
    max_epochs = max(1, int(request.max_epochs or YOLO11_DETECTION_DEFAULT_MAX_EPOCHS))
    evaluation_interval = max(
        1,
        int(
            request.evaluation_interval or YOLO11_DETECTION_DEFAULT_EVALUATION_INTERVAL
        ),
    )
    extra_options = dict(request.extra_options or {})
    device, gpu_count, device_ids, distributed_mode, runtime_precision = (
        resolve_yolo11_detection_runtime(
            imports=imports,
            requested_gpu_count=request.gpu_count,
            requested_precision=request.precision,
            extra_options=extra_options,
        )
    )
    training_options = _resolve_yolo11_detection_training_options(extra_options)
    augmentation_options = build_yolo11_task_augmentation_options(extra_options)
    validation_split_name = (
        validation_split.name if validation_split is not None else None
    )

    model = build_yolo11_model(
        task_type="detection",
        model_scale=request.model_scale,
        num_classes=len(category_names),
    )
    warm_start_summary = _resolve_yolo11_warm_start_summary(
        imports=imports,
        model=model,
        request=request,
    )
    parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
    training_runtime = build_yolo11_detection_training_runtime(
        torch_module=imports.torch,
        model=model,
        learning_rate=training_options["learning_rate"],
        weight_decay=training_options["weight_decay"],
        max_epochs=max_epochs,
        min_lr_ratio=training_options["min_lr_ratio"],
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

    resume_state = None
    if request.resume_checkpoint_path is not None:
        resume_state = _load_yolo11_resume_checkpoint(
            imports=imports,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            checkpoint_path=request.resume_checkpoint_path,
            expected_model_type="yolo11",
            expected_model_scale=request.model_scale,
            expected_num_classes=len(category_names),
            expected_input_size=input_size,
            expected_batch_size=batch_size,
            expected_max_epochs=max_epochs,
            expected_precision=runtime_precision,
            expected_validation_split_name=validation_split_name,
            expected_evaluation_interval=evaluation_interval,
            expected_evaluation_confidence_threshold=(
                training_options["evaluation_confidence_threshold"]
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            expected_evaluation_nms_threshold=(
                training_options["evaluation_nms_threshold"]
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            expected_learning_rate=training_options["learning_rate"],
            expected_weight_decay=training_options["weight_decay"],
            expected_class_loss_weight=training_options["class_loss_weight"],
            expected_box_loss_weight=training_options["box_loss_weight"],
            expected_dfl_loss_weight=training_options["dfl_loss_weight"],
            expected_assign_topk=training_options["assign_topk"],
            expected_assign_alpha=training_options["assign_alpha"],
            expected_assign_beta=training_options["assign_beta"],
            expected_min_lr_ratio=training_options["min_lr_ratio"],
            expected_grad_clip_norm=training_options["grad_clip_norm"],
        )
        warm_start_summary = dict(resume_state.warm_start_summary)

    model.to(device)
    if runtime_precision == "fp16":
        model.half()
    if resume_state is not None:
        move_yolo11_optimizer_state_to_device(optimizer=optimizer, device=device)
    ema = YoloModelEMA(
        model=model,
        updates=resume_state.ema_updates if resume_state is not None else 0,
    )
    if resume_state is not None and resume_state.ema_state_dict is not None:
        ema.load_state_dict(resume_state.ema_state_dict, strict=False)

    autocast_context = build_yolo11_autocast_context(
        torch_module=imports.torch,
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
    execution_plan = plan_yolo11_detection_training_execution(
        train_sample_count=len(train_samples),
        validation_sample_count=len(validation_samples),
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
    latest_checkpoint_bytes = b""
    best_checkpoint_bytes = (
        _build_yolo11_checkpoint_bytes_from_state(
            imports=imports,
            checkpoint_state=resume_state.best_checkpoint_state,
        )
        if resume_state is not None and resume_state.best_checkpoint_state is not None
        else b""
    )

    def _build_training_batch_for_epoch(
        sample_batch: list[Any],
        available_samples: tuple[Any, ...],
        current_epoch: int,
    ) -> tuple[Any, tuple[Any, ...]]:
        """按当前 epoch 构造 YOLO11 detection 训练 batch。"""

        effective_augmentation_options = resolve_yolo11_task_augmentation_for_epoch(
            augmentation_options=augmentation_options,
            epoch_index=max(0, int(current_epoch) - 1),
            max_epochs=max_epochs,
        )
        return build_yolo11_detection_training_batch(
            imports=imports,
            samples=sample_batch,
            input_size=resolve_yolo11_task_batch_input_size(
                base_input_size=input_size,
                augmentation_options=effective_augmentation_options,
            ),
            device=device,
            runtime_precision=runtime_precision,
            augment_training=True,
            available_samples=available_samples,
            augmentation_options=effective_augmentation_options,
        )

    try:
        loop_result = run_yolo11_detection_training_loop(
            torch_module=imports.torch,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            training_schedule=training_schedule,
            ema=ema,
            train_samples=train_samples,
            validation_samples=validation_samples,
            batch_size=batch_size,
            input_size=input_size,
            max_epochs=max_epochs,
            resume_epoch=resume_state.resume_epoch if resume_state is not None else 0,
            initial_global_iteration=execution_plan.initial_global_iteration,
            total_iterations=execution_plan.total_iterations,
            autocast_context=autocast_context,
            build_batch=_build_training_batch_for_epoch,
            unwrap_outputs=unwrap_yolo11_detection_outputs,
            compute_loss=lambda **kwargs: _compute_yolo11_detection_loss(
                imports=imports,
                num_classes=len(category_names),
                class_loss_weight=training_options["class_loss_weight"],
                box_loss_weight=training_options["box_loss_weight"],
                dfl_loss_weight=training_options["dfl_loss_weight"],
                assign_topk=training_options["assign_topk"],
                assign_alpha=training_options["assign_alpha"],
                assign_beta=training_options["assign_beta"],
                **kwargs,
            ),
            evaluate_model=lambda: _evaluate_yolo11_detection_model(
                imports=imports,
                model=ema.model,
                samples=validation_samples,
                category_ids=category_ids,
                annotation_file=(
                    validation_split.annotation_file
                    if validation_split is not None
                    else None
                ),
                annotation_payload=(
                    validation_split.annotation_payload
                    if validation_split is not None
                    else None
                ),
                input_size=input_size,
                batch_size=batch_size,
                device=device,
                runtime_precision=runtime_precision,
                num_classes=len(category_names),
                class_loss_weight=training_options["class_loss_weight"],
                box_loss_weight=training_options["box_loss_weight"],
                dfl_loss_weight=training_options["dfl_loss_weight"],
                assign_topk=training_options["assign_topk"],
                assign_alpha=training_options["assign_alpha"],
                assign_beta=training_options["assign_beta"],
                confidence_threshold=training_options[
                    "evaluation_confidence_threshold"
                ],
                nms_threshold=training_options["evaluation_nms_threshold"],
            ),
            grad_clip_norm=training_options["grad_clip_norm"],
            category_names=category_names,
            model_scale=request.model_scale,
            precision=runtime_precision,
            validation_split_name=validation_split_name,
            evaluation_interval=evaluation_interval,
            evaluation_confidence_threshold=(
                training_options["evaluation_confidence_threshold"]
                if has_validation
                else None
            ),
            evaluation_nms_threshold=(
                training_options["evaluation_nms_threshold"] if has_validation else None
            ),
            learning_rate=training_options["learning_rate"],
            weight_decay=training_options["weight_decay"],
            class_loss_weight=training_options["class_loss_weight"],
            box_loss_weight=training_options["box_loss_weight"],
            dfl_loss_weight=training_options["dfl_loss_weight"],
            assign_topk=training_options["assign_topk"],
            assign_alpha=training_options["assign_alpha"],
            assign_beta=training_options["assign_beta"],
            min_lr_ratio=training_options["min_lr_ratio"],
            warm_start_summary=warm_start_summary,
            implementation_mode=request.implementation_mode,
            augmentation_options=serialize_yolo11_detection_augmentation_options(
                augmentation_options
            ),
            has_validation=has_validation,
            best_metric_name=best_metric_name,
            best_metric_value=best_metric_value,
            metrics_history=metrics_history,
            validation_history=validation_history,
            evaluated_epochs=evaluated_epochs,
            previous_best_checkpoint_bytes=best_checkpoint_bytes,
            batch_callback=(
                _build_yolo11_batch_progress_adapter(request.batch_callback)
                if request.batch_callback is not None
                else None
            ),
            epoch_callback=(
                _build_yolo11_epoch_progress_adapter(request.epoch_callback)
                if request.epoch_callback is not None
                else None
            ),
            savepoint_callback=(
                _build_yolo11_savepoint_adapter(request.savepoint_callback)
                if request.savepoint_callback is not None
                else None
            ),
        )
    except Yolo11DetectionTrainingPausedError as error:
        raise YoloDetectionTrainingPausedError(
            YoloDetectionTrainingSavePoint(
                epoch=error.savepoint.epoch,
                latest_checkpoint_bytes=error.savepoint.latest_checkpoint_bytes,
                best_checkpoint_bytes=error.savepoint.best_checkpoint_bytes,
                best_metric_name=error.savepoint.best_metric_name,
                best_metric_value=error.savepoint.best_metric_value,
            )
        ) from error
    except Yolo11DetectionTrainingTerminatedError as error:
        raise YoloDetectionTrainingTerminatedError() from error

    latest_checkpoint_bytes = loop_result.latest_checkpoint_bytes
    best_checkpoint_bytes = loop_result.best_checkpoint_bytes or latest_checkpoint_bytes
    best_metric_name = loop_result.best_metric_name
    best_metric_value = _normalize_yolo11_best_metric_value(
        value=loop_result.best_metric_value,
        has_validation=has_validation,
    )
    metrics_history = loop_result.metrics_history
    validation_history = loop_result.validation_history
    evaluated_epochs = loop_result.evaluated_epochs

    validation_metrics_payload = _build_yolo11_validation_metrics_payload(
        validation_split_name=validation_split_name,
        validation_sample_count=len(validation_samples),
        evaluation_interval=evaluation_interval,
        confidence_threshold=training_options["evaluation_confidence_threshold"],
        nms_threshold=training_options["evaluation_nms_threshold"],
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        evaluated_epochs=evaluated_epochs,
        validation_history=validation_history,
    )
    metrics_payload = _build_yolo11_metrics_payload(
        request=request,
        resolved_splits=resolved_splits,
        train_split_name=train_split.name,
        validation_split_name=validation_split_name,
        train_sample_count=len(train_samples),
        validation_sample_count=len(validation_samples),
        category_names=category_names,
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        evaluation_interval=evaluation_interval,
        device=device,
        gpu_count=gpu_count,
        device_ids=device_ids,
        distributed_mode=distributed_mode,
        runtime_precision=runtime_precision,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        metrics_history=metrics_history,
        parameter_count=parameter_count,
        warm_start_summary=warm_start_summary,
        training_options=training_options,
        optimizer=optimizer,
        training_schedule=training_runtime.schedule,
        validation_metrics_payload=validation_metrics_payload,
        augmentation_options=augmentation_options,
    )
    return Yolo11DetectionTrainingExecutionResult(
        checkpoint_bytes=best_checkpoint_bytes,
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload=metrics_payload,
        validation_metrics_payload=validation_metrics_payload,
        warm_start_summary=warm_start_summary,
        implementation_mode=request.implementation_mode,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
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
        validation_split_name=validation_split_name,
        validation_sample_count=len(validation_samples),
        parameter_count=parameter_count,
    )


def _require_yolo11_detection_request(
    request: Yolo11DetectionTrainingExecutionRequest,
) -> None:
    """确认当前执行入口只接收 YOLO11 detection 请求。"""

    if request.model_type != "yolo11":
        raise InvalidRequestError(
            "YOLO11 detection 训练入口只支持 yolo11 model_type",
            details={"model_type": request.model_type},
        )


def _resolve_yolo11_detection_training_options(
    extra_options: dict[str, object],
) -> dict[str, Any]:
    """解析 YOLO11 detection 训练参数。"""

    return {
        "learning_rate": read_yolo11_float_option(
            extra_options, "learning_rate", default=0.01
        ),
        "weight_decay": read_yolo11_float_option(
            extra_options, "weight_decay", default=5e-4
        ),
        "class_loss_weight": read_yolo11_float_option(
            extra_options,
            "class_loss_weight",
            default=YOLO11_DETECTION_DEFAULT_CLASS_LOSS_WEIGHT,
        ),
        "box_loss_weight": read_yolo11_float_option(
            extra_options,
            "box_loss_weight",
            default=YOLO11_DETECTION_DEFAULT_BOX_LOSS_WEIGHT,
        ),
        "dfl_loss_weight": read_yolo11_float_option(
            extra_options,
            "dfl_loss_weight",
            default=YOLO11_DETECTION_DEFAULT_DFL_LOSS_WEIGHT,
        ),
        "evaluation_confidence_threshold": read_yolo11_float_option(
            extra_options,
            "evaluation_confidence_threshold",
            default=YOLO11_DETECTION_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
        ),
        "evaluation_nms_threshold": read_yolo11_float_option(
            extra_options,
            "evaluation_nms_threshold",
            default=YOLO11_DETECTION_DEFAULT_EVAL_NMS_THRESHOLD,
        ),
        "assign_topk": max(
            1,
            read_yolo11_int_option(
                extra_options,
                "assign_topk",
                default=YOLO11_DETECTION_DEFAULT_ASSIGN_TOPK,
            ),
        ),
        "assign_alpha": read_yolo11_float_option(
            extra_options,
            "assign_alpha",
            default=YOLO11_DETECTION_DEFAULT_ASSIGN_ALPHA,
        ),
        "assign_beta": read_yolo11_float_option(
            extra_options,
            "assign_beta",
            default=YOLO11_DETECTION_DEFAULT_ASSIGN_BETA,
        ),
        "min_lr_ratio": read_yolo11_float_option(
            extra_options,
            "min_lr_ratio",
            default=YOLO11_DETECTION_DEFAULT_MIN_LR_RATIO,
        ),
        "grad_clip_norm": read_yolo11_float_option(
            extra_options,
            "grad_clip_norm",
            default=YOLO11_DETECTION_DEFAULT_GRAD_CLIP_NORM,
        ),
    }


def _resolve_yolo11_warm_start_summary(
    *,
    imports: Any,
    model: Any,
    request: Yolo11DetectionTrainingExecutionRequest,
) -> dict[str, object]:
    """加载 YOLO11 warm start 并返回摘要。"""

    if request.warm_start_checkpoint_path is None:
        return build_yolo_disabled_warm_start_summary()
    load_result = load_yolo11_checkpoint_file(
        torch_module=imports.torch,
        model=model,
        checkpoint_path=request.warm_start_checkpoint_path,
        minimum_loadable_ratio=YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
        strict_shape=False,
    )
    return build_yolo_warm_start_summary(
        load_result=load_result,
        source_summary=request.warm_start_source_summary,
    )


def _load_yolo11_resume_checkpoint(
    *,
    imports: Any,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    checkpoint_path: Any,
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
) -> _Yolo11LoadedResumeState:
    """加载并校验 YOLO11 detection resume checkpoint。"""

    checkpoint_payload = imports.torch.load(checkpoint_path, map_location="cpu")
    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError("YOLO11 resume checkpoint 内容不合法")
    validate_yolo11_detection_resume_checkpoint(
        checkpoint_payload=checkpoint_payload,
        request=Yolo11DetectionResumeValidationRequest(
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
    model.load_state_dict(dict(checkpoint_payload.get("model_state_dict") or {}))
    optimizer_state_dict = checkpoint_payload.get("optimizer_state_dict")
    if isinstance(optimizer_state_dict, dict):
        optimizer.load_state_dict(optimizer_state_dict)
    scheduler_state_dict = checkpoint_payload.get("scheduler_state_dict")
    if not isinstance(scheduler_state_dict, dict):
        raise InvalidRequestError("YOLO11 resume checkpoint 缺少 scheduler_state_dict")
    scheduler.load_state_dict(scheduler_state_dict)
    scaler_state_dict = checkpoint_payload.get("scaler_state_dict")
    if not isinstance(scaler_state_dict, dict):
        raise InvalidRequestError("YOLO11 resume checkpoint 缺少 scaler_state_dict")
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
    ema_state_dict = checkpoint_payload.get("ema_state_dict")
    raw_ema_updates = checkpoint_payload.get("ema_updates")
    return _Yolo11LoadedResumeState(
        resume_epoch=resume_epoch,
        epoch_history=_normalize_yolo11_history_items(
            checkpoint_payload.get("metrics_history")
        ),
        validation_history=_normalize_yolo11_history_items(
            checkpoint_payload.get("validation_history")
        ),
        evaluated_epochs=_normalize_yolo11_evaluated_epochs(
            checkpoint_payload.get("evaluated_epochs")
        ),
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=(
            dict(checkpoint_payload.get("best_checkpoint_state"))
            if isinstance(checkpoint_payload.get("best_checkpoint_state"), dict)
            else None
        ),
        ema_state_dict=(
            dict(ema_state_dict)
            if isinstance(ema_state_dict, dict)
            else None
        ),
        ema_updates=(
            int(raw_ema_updates)
            if isinstance(raw_ema_updates, int) and raw_ema_updates >= 0
            else 0
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


def _build_yolo11_checkpoint_bytes_from_state(
    *,
    imports: Any,
    checkpoint_state: dict[str, object] | None,
) -> bytes:
    """把 YOLO11 detection checkpoint state 重新编码为 bytes。"""

    return encode_yolo11_detection_checkpoint_state(
        torch_module=imports.torch,
        checkpoint_state=checkpoint_state,
    )


def _compute_yolo11_detection_loss(
    *,
    imports: Any,
    model: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[Any, ...],
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """调用 YOLO11 core 计算 detection loss。"""

    del num_classes
    return compute_yolo11_detection_training_loss(
        torch_module=imports.torch,
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


def _evaluate_yolo11_detection_model(
    *,
    imports: Any,
    model: Any,
    samples: tuple[Any, ...],
    category_ids: tuple[int, ...],
    annotation_file: Any,
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
    """执行 YOLO11 detection validation loss 与 COCO bbox mAP。"""

    validation_losses = evaluate_yolo11_detection_validation_losses(
        torch_module=imports.torch,
        model=model,
        samples=samples,
        batch_size=batch_size,
        build_batch=lambda batch_samples: build_yolo11_detection_training_batch(
            imports=imports,
            samples=batch_samples,
            input_size=input_size,
            device=device,
            runtime_precision=runtime_precision,
            augment_training=False,
        ),
        unwrap_outputs=unwrap_yolo11_detection_outputs,
        compute_loss=lambda **kwargs: _compute_yolo11_detection_loss(
            imports=imports,
            num_classes=num_classes,
            **kwargs,
        ),
        autocast_context=lambda: build_yolo11_autocast_context(
            torch_module=imports.torch,
            device=device,
            runtime_precision=runtime_precision,
        )(),
        freeze_batch_norm=lambda: _freeze_yolo11_batch_norm_modules(
            imports=imports,
            model=model,
        ),
        restore_batch_norm=_restore_yolo11_batch_norm_modules,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
    )
    validation_map = _evaluate_yolo11_validation_map(
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
    return {
        "loss": round(float(validation_losses.get("loss", 0.0)), 6),
        "class_loss": round(float(validation_losses.get("class_loss", 0.0)), 6),
        "box_loss": round(float(validation_losses.get("box_loss", 0.0)), 6),
        "dfl_loss": round(float(validation_losses.get("dfl_loss", 0.0)), 6),
        "map50": round(float(validation_map.get("map50", 0.0)), 6),
        "map50_95": round(float(validation_map.get("map50_95", 0.0)), 6),
        "sample_count": len(samples),
    }


def _evaluate_yolo11_validation_map(
    *,
    imports: Any,
    model: Any,
    samples: tuple[Any, ...],
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    category_ids: tuple[int, ...],
    annotation_file: Any,
    annotation_payload: dict[str, object] | None,
    confidence_threshold: float,
    nms_threshold: float,
) -> dict[str, float]:
    """执行 YOLO11 detection COCO bbox mAP。"""

    if not samples or annotation_payload is None:
        return {"map50": 0.0, "map50_95": 0.0}
    if imports.COCO is None or imports.COCOeval is None:
        raise ServiceConfigurationError(
            "当前环境缺少 pycocotools，无法执行 YOLO11 detection mAP 验证"
        )

    previous_training_mode = bool(model.training)
    model.eval()
    detections: list[dict[str, object]] = []
    try:
        with imports.torch.no_grad():
            for batch_samples in _iter_yolo11_batches(samples, batch_size):
                images, batch_targets = build_yolo11_detection_training_batch(
                    imports=imports,
                    samples=batch_samples,
                    input_size=input_size,
                    device=device,
                    runtime_precision=runtime_precision,
                    augment_training=False,
                )
                prediction_tensor = model(images)
                detections.extend(
                    convert_yolo11_predictions_to_coco_detections(
                        np_module=imports.np,
                        prediction_tensor=prediction_tensor,
                        batch_targets=batch_targets,
                        input_size=input_size,
                        category_ids=category_ids,
                        confidence_threshold=confidence_threshold,
                        nms_threshold=nms_threshold,
                    )
                )
    finally:
        model.train(previous_training_mode)

    if not detections:
        return {"map50": 0.0, "map50_95": 0.0}

    ground_truth = _load_yolo11_coco_ground_truth_silently(
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


def _load_yolo11_coco_ground_truth_silently(
    *,
    imports: Any,
    annotation_file: Any,
    annotation_payload: dict[str, object] | None,
) -> Any:
    """静默加载 YOLO11 validation 使用的 COCO ground truth。"""

    if imports.COCO is None:
        raise ServiceConfigurationError("当前环境缺少 pycocotools.COCO")
    with redirect_stdout(io.StringIO()):
        if annotation_file is not None:
            return imports.COCO(str(annotation_file))
        if annotation_payload is None:
            raise InvalidRequestError("缺少可用的 YOLO11 COCO ground truth 数据")
        ground_truth = imports.COCO()
        ground_truth.dataset = annotation_payload
        ground_truth.createIndex()
        return ground_truth


def _iter_yolo11_batches(samples: tuple[Any, ...], batch_size: int):
    """按 batch size 迭代 YOLO11 样本。"""

    sample_list = list(samples)
    resolved_batch_size = max(1, int(batch_size))
    for start in range(0, len(sample_list), resolved_batch_size):
        yield sample_list[start : start + resolved_batch_size]


def _freeze_yolo11_batch_norm_modules(
    *,
    imports: Any,
    model: Any,
) -> tuple[tuple[Any, bool], ...]:
    """在 YOLO11 validation loss 统计阶段冻结 BatchNorm。"""

    batch_norm_states: list[tuple[Any, bool]] = []
    for module in model.modules():
        if isinstance(module, imports.torch.nn.BatchNorm2d):
            batch_norm_states.append((module, bool(module.training)))
            module.eval()
    return tuple(batch_norm_states)


def _restore_yolo11_batch_norm_modules(
    batch_norm_states: tuple[tuple[Any, bool], ...],
) -> None:
    """恢复 YOLO11 validation 前的 BatchNorm 状态。"""

    for module, was_training in batch_norm_states:
        module.train(was_training)


def _normalize_yolo11_history_items(value: object) -> list[dict[str, object]]:
    """把 YOLO11 checkpoint 指标历史归一成列表。"""

    if not isinstance(value, list):
        return []
    normalized_items: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            normalized_items.append(
                {str(key): current_value for key, current_value in item.items()}
            )
    return normalized_items


def _normalize_yolo11_evaluated_epochs(value: object) -> tuple[int, ...]:
    """把 YOLO11 checkpoint 中的验证 epoch 归一成整数元组。"""

    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and item > 0)


def _build_yolo11_batch_progress_adapter(callback):
    """把 YOLO11 core batch 进度转成平台 batch 进度。"""

    def on_yolo11_batch_progress(
        progress: Yolo11DetectionTrainingBatchProgress,
    ) -> None:
        callback(
            YoloDetectionTrainingBatchProgress(
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

    return on_yolo11_batch_progress


def _build_yolo11_epoch_progress_adapter(callback):
    """把 YOLO11 core epoch 进度转成平台 epoch 控制命令。"""

    def on_yolo11_epoch_progress(progress: Yolo11DetectionTrainerEpochProgress):
        control_command = callback(
            YoloDetectionTrainingEpochProgress(
                epoch=progress.epoch,
                max_epochs=progress.max_epochs,
                evaluation_interval=progress.evaluation_interval,
                validation_ran=progress.validation_ran,
                evaluated_epochs=progress.evaluated_epochs,
                train_metrics=progress.train_metrics,
                validation_metrics=progress.validation_metrics,
                train_metrics_snapshot=progress.train_metrics_snapshot,
                validation_snapshot=progress.validation_snapshot,
                current_metric_name=progress.current_metric_name,
                current_metric_value=progress.current_metric_value,
                best_metric_name=progress.best_metric_name,
                best_metric_value=progress.best_metric_value,
            )
        )
        return resolve_yolo11_detection_epoch_control(
            save_checkpoint_requested=_read_control_flag(
                control_command, "save_checkpoint"
            ),
            pause_training_requested=_read_control_flag(
                control_command, "pause_training"
            ),
            terminate_training_requested=_read_control_flag(
                control_command, "terminate_training"
            ),
        )

    return on_yolo11_epoch_progress


def _build_yolo11_savepoint_adapter(callback):
    """把 YOLO11 core savepoint 转成平台 savepoint。"""

    def on_yolo11_savepoint(savepoint_payload) -> None:
        callback(
            YoloDetectionTrainingSavePoint(
                epoch=savepoint_payload.epoch,
                latest_checkpoint_bytes=savepoint_payload.latest_checkpoint_bytes,
                best_checkpoint_bytes=savepoint_payload.best_checkpoint_bytes,
                best_metric_name=savepoint_payload.best_metric_name,
                best_metric_value=savepoint_payload.best_metric_value,
            )
        )

    return on_yolo11_savepoint


def _read_control_flag(
    control_command: YoloDetectionTrainingControlCommand | None,
    field_name: str,
) -> bool:
    """读取平台训练控制命令中的布尔字段。"""

    if control_command is None:
        return False
    return bool(getattr(control_command, field_name))


def _normalize_yolo11_best_metric_value(*, value: float, has_validation: bool) -> float:
    """把 YOLO11 best metric 哨兵值转成平台可展示数值。"""

    if has_validation and value == float("-inf"):
        return 0.0
    if not has_validation and value == float("inf"):
        return 0.0
    return round(float(value), 6)


def _build_yolo11_validation_metrics_payload(
    *,
    validation_split_name: str | None,
    validation_sample_count: int,
    evaluation_interval: int,
    confidence_threshold: float,
    nms_threshold: float,
    best_metric_name: str,
    best_metric_value: float,
    evaluated_epochs: list[int],
    validation_history: list[dict[str, object]],
) -> dict[str, object]:
    """组装 YOLO11 validation metrics payload。"""

    enabled = validation_split_name is not None and validation_sample_count > 0
    return {
        "enabled": enabled,
        "evaluation_interval": evaluation_interval,
        "split_name": validation_split_name,
        "sample_count": validation_sample_count,
        "confidence_threshold": confidence_threshold if enabled else None,
        "nms_threshold": nms_threshold if enabled else None,
        "postprocess_mode": YOLO11_DETECTION_POSTPROCESS_MODE_NMS if enabled else None,
        "max_detections": None,
        "best_metric_name": best_metric_name if enabled else None,
        "best_metric_value": best_metric_value if enabled else None,
        "evaluated_epochs": evaluated_epochs,
        "epoch_history": validation_history,
        "final_metrics": validation_history[-1] if validation_history else {},
    }


def _build_yolo11_metrics_payload(
    *,
    request: Yolo11DetectionTrainingExecutionRequest,
    resolved_splits: tuple[Any, ...],
    train_split_name: str,
    validation_split_name: str | None,
    train_sample_count: int,
    validation_sample_count: int,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    batch_size: int,
    max_epochs: int,
    evaluation_interval: int,
    device: str,
    gpu_count: int,
    device_ids: tuple[int, ...],
    distributed_mode: str,
    runtime_precision: str,
    best_metric_name: str,
    best_metric_value: float,
    metrics_history: list[dict[str, object]],
    parameter_count: int,
    warm_start_summary: dict[str, object],
    training_options: dict[str, Any],
    optimizer: Any,
    training_schedule: YoloUltralyticsTrainingSchedule,
    validation_metrics_payload: dict[str, object],
    augmentation_options: Any,
) -> dict[str, object]:
    """组装 YOLO11 detection training metrics payload。"""

    return {
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
        "train_split_name": train_split_name,
        "validation_split_name": validation_split_name,
        "sample_count": sum(split.sample_count for split in resolved_splits),
        "train_sample_count": train_sample_count,
        "validation_sample_count": validation_sample_count,
        "category_names": list(category_names),
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "epoch_history": metrics_history,
        "final_metrics": metrics_history[-1] if metrics_history else {},
        "parameter_count": parameter_count,
        "warm_start": warm_start_summary,
        "optimizer": {
            "name": training_schedule.optimizer_name,
            "learning_rate": training_schedule.initial_lr,
            "weight_decay": training_schedule.weight_decay,
            "scaled_weight_decay": training_schedule.scaled_weight_decay,
            "nominal_batch_size": training_schedule.nominal_batch_size,
            "accumulate": training_schedule.accumulate,
        },
        "scheduler": {
            "name": "UltralyticsCosineLambdaLR",
            "min_lr_ratio": training_options["min_lr_ratio"],
            "warmup_iterations": training_schedule.warmup_iterations,
            "warmup_momentum": training_schedule.warmup_momentum,
            "warmup_bias_lr": training_schedule.warmup_bias_lr,
            "latest_learning_rate": float(optimizer.param_groups[0]["lr"]),
        },
        "evaluation": {
            "split_name": validation_split_name,
            "confidence_threshold": (
                training_options["evaluation_confidence_threshold"]
                if validation_sample_count > 0
                else None
            ),
            "nms_threshold": (
                training_options["evaluation_nms_threshold"]
                if validation_sample_count > 0
                else None
            ),
            "postprocess_mode": YOLO11_DETECTION_POSTPROCESS_MODE_NMS,
            "max_detections": None,
        },
        "loss_weights": {
            "class_loss_weight": training_options["class_loss_weight"],
            "box_loss_weight": training_options["box_loss_weight"],
            "dfl_loss_weight": training_options["dfl_loss_weight"],
        },
        "assignment": {
            "assign_topk": training_options["assign_topk"],
            "assign_alpha": training_options["assign_alpha"],
            "assign_beta": training_options["assign_beta"],
        },
        "gradient_control": {
            "grad_clip_norm": training_options["grad_clip_norm"],
        },
        "augmentation": serialize_yolo11_detection_augmentation_options(
            augmentation_options
        ),
        "validation": validation_metrics_payload,
    }


__all__ = [
    "YOLO11_IMPLEMENTATION_MODE",
    "Yolo11DetectionTrainingExecutionRequest",
    "Yolo11DetectionTrainingExecutionResult",
    "Yolo11TrainingBatchProgress",
    "Yolo11TrainingEpochProgress",
    "run_yolo11_detection_training",
]
