"""YOLO11 classification 专属训练执行入口。"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.amp_policy import (
    resolve_training_amp_runtime,
)
from backend.service.application.models.training.batch_policy import (
    read_resume_checkpoint_batch_size,
    resolve_training_batch_size,
)
from backend.service.application.models.training.training_engine import (
    training_engine_entrypoint,
)
from backend.service.application.models.training.checkpoint_policy import (
    read_training_checkpoint_interval,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloModelEMA,
    YoloTaskTrainingBatchProgress,
    resolve_yolo_optimizer_base_learning_rate,
)
from backend.service.application.models.training.classification_evaluation_report import (
    build_unavailable_test_metrics_report,
)
from backend.service.application.models.yolo_core_common.data import (
    build_yolo_classification_augmentation_options,
    build_yolo_classification_augmentation_summary,
)
from backend.service.application.models.yolo_core_common.training import (
    resolve_yolo_classification_dataloader_plan,
)
from backend.service.application.models.yolo11_core import build_yolo11_model
from backend.service.application.models.yolo11_core.data import (
    load_yolo11_classification_training_manifest,
)
from backend.service.application.models.yolo11_core.training.classification_checkpoint import (
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
from backend.service.application.models.yolo11_core.training.classification_runtime import (
    build_yolo11_classification_training_runtime,
    move_yolo11_classification_optimizer_state_to_device,
    resolve_yolo11_classification_training_device,
)
from backend.service.application.models.yolo11_core.training.classification_trainer import (
    Yolo11ClassificationTrainingControlCommand,
    Yolo11ClassificationTrainingEpochProgress,
    Yolo11ClassificationTrainingPausedError as CoreYolo11ClassificationTrainingPausedError,
    Yolo11ClassificationTrainingSavePoint,
    Yolo11ClassificationTrainingTerminatedError as CoreYolo11ClassificationTrainingTerminatedError,
    run_yolo11_classification_training_loop,
)
from backend.service.application.models.yolo11_core.training.classification_imports import (
    require_yolo11_classification_training_imports,
)
from backend.service.application.models.yolo11_core.weights import (
    load_yolo11_checkpoint_file,
)
from backend.service.application.models.yolo11_core.evaluation import (
    evaluate_yolo11_classification_samples,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO11_CLASSIFICATION_IMPLEMENTATION_MODE = "yolo11-classification-core"


@dataclass(frozen=True)
class Yolo11ClassificationTrainingExecutionRequest:
    """描述一次 YOLO11 classification 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int
    max_epochs: int
    evaluation_interval: int
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    previous_best_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: (
        Callable[
            [Yolo11ClassificationTrainingEpochProgress],
            Yolo11ClassificationTrainingControlCommand | None,
        ]
        | None
    ) = None
    batch_callback: Callable[[YoloTaskTrainingBatchProgress], None] | None = None
    savepoint_callback: (
        Callable[[Yolo11ClassificationTrainingSavePoint], None] | None
    ) = None
    control_callback: Callable[[], None] | None = None


@dataclass(frozen=True)
class Yolo11ClassificationTrainingExecutionResult:
    """描述一次 YOLO11 classification 训练执行结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    warm_start_summary: dict[str, object]
    best_checkpoint_bytes: bytes | None = None
    test_metrics_payload: dict[str, object] | None = None


class Yolo11ClassificationTrainingPausedError(Exception):
    """YOLO11 classification 训练被显式暂停。"""


class Yolo11ClassificationTrainingTerminatedError(Exception):
    """YOLO11 classification 训练被显式终止。"""


@training_engine_entrypoint
def run_yolo11_classification_training(
    request: Yolo11ClassificationTrainingExecutionRequest,
) -> Yolo11ClassificationTrainingExecutionResult:
    """执行一次 YOLO11 classification 训练。"""

    if request.model_type != "yolo11":
        raise InvalidRequestError(
            "YOLO11 classification 训练入口只接受 model_type=yolo11",
            details={"model_type": request.model_type},
        )

    imports = require_yolo11_classification_training_imports()
    device_name = resolve_yolo11_classification_training_device(
        torch_module=imports.torch,
        extra_options=request.extra_options,
    )
    precision = resolve_training_amp_runtime(
        torch_module=imports.torch,
        device_name=device_name,
        requested_precision=request.precision,
        extra_options=request.extra_options,
    ).precision
    input_size = request.input_size or YOLO11_CLASSIFICATION_DEFAULT_INPUT_SIZE

    resolved_manifest = load_yolo11_classification_training_manifest(
        dataset_storage=request.dataset_storage,
        manifest_payload=request.manifest_payload,
    )
    labels = resolved_manifest.labels
    train_annotations = resolved_manifest.train_annotations
    val_annotations = resolved_manifest.val_annotations
    test_annotations = resolved_manifest.test_annotations

    model = build_yolo11_model(
        task_type=CLASSIFICATION_TASK_TYPE,
        model_scale=request.model_scale,
        num_classes=len(labels),
    )

    warm_start_summary = build_yolo_disabled_warm_start_summary()
    if (
        request.resume_checkpoint_path is None
        and request.warm_start_checkpoint_path is not None
        and request.warm_start_checkpoint_path.is_file()
    ):
        load_result = load_yolo11_checkpoint_file(
            torch_module=imports.torch,
            model=model,
            checkpoint_path=request.warm_start_checkpoint_path,
            minimum_loadable_ratio=YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
            strict_shape=False,
            restore_checkpoint_attributes=False,
        )
        warm_start_summary = build_yolo_warm_start_summary(
            load_result=load_result,
            source_summary=request.warm_start_source_summary,
        )

    resume_state = None
    if (
        request.resume_checkpoint_path is not None
        and request.resume_checkpoint_path.is_file()
    ):
        resume_state = load_yolo11_classification_resume_state(
            checkpoint_path=request.resume_checkpoint_path,
            torch_module=imports.torch,
        )

    extra = request.extra_options or {}
    learning_rate = float(extra.get("learning_rate", YOLO11_CLASSIFICATION_DEFAULT_LR))
    weight_decay = float(
        extra.get(
            "weight_decay",
            YOLO11_CLASSIFICATION_DEFAULT_WEIGHT_DECAY,
        )
    )
    min_lr_ratio = float(
        extra.get(
            "min_lr_ratio",
            YOLO11_CLASSIFICATION_DEFAULT_MIN_LR_RATIO,
        )
    )
    batch_size = int(extra.get("batch_size", request.batch_size))
    max_epochs = int(extra.get("max_epochs", request.max_epochs))
    evaluation_interval = int(
        extra.get("evaluation_interval", request.evaluation_interval)
    )
    augmentation_options = build_yolo_classification_augmentation_options(extra)
    dataloader_plan = resolve_yolo_classification_dataloader_plan(
        extra_options=extra,
        device=device_name,
    )

    if resume_state is not None:
        validate_yolo11_classification_resume_parameters(
            resume_state,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
        )

    model.to(device_name)
    batch_size = resolve_training_batch_size(
        torch_module=imports.torch,
        model=model,
        device_name=device_name,
        input_size=input_size,
        dataset_size=len(train_annotations),
        requested_batch_size=request.batch_size,
        default_batch_size=16,
        runtime_precision=precision,
        extra_options=extra,
        resume_batch_size=read_resume_checkpoint_batch_size(
            torch_module=imports.torch,
            checkpoint_path=request.resume_checkpoint_path,
        ),
    ).batch_size
    runtime = build_yolo11_classification_training_runtime(
        torch_module=imports.torch,
        model=model,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        min_lr_ratio=min_lr_ratio,
        batch_size=batch_size,
        max_epochs=max_epochs,
        train_sample_count=len(train_annotations),
        device_name=device_name,
        precision=precision,
        num_classes=len(labels),
        optimizer_name=str(extra.get("optimizer", "auto")),
        cosine_schedule=bool(extra.get("cos_lr", False)),
    )

    start_epoch = 0
    global_iteration = 0
    metrics_history: list[dict[str, float]] = []
    validation_history: list[dict[str, float]] = []
    best_metric_value = -1.0
    best_metric_name = "val_top1_accuracy"
    if resume_state is not None:
        load_yolo11_classification_model_state(
            model=model,
            state_dict=resume_state.model_state_dict,
            device_name=device_name,
        )
        runtime.optimizer.load_state_dict(resume_state.optimizer_state_dict)
        move_yolo11_classification_optimizer_state_to_device(
            optimizer=runtime.optimizer,
            device_name=device_name,
        )
        if resume_state.scheduler_state_dict is not None:
            runtime.scheduler.load_state_dict(resume_state.scheduler_state_dict)
        if resume_state.scaler_state_dict is not None and runtime.scaler is not None:
            runtime.scaler.load_state_dict(resume_state.scaler_state_dict)
        metrics_history = list(resume_state.metrics_history)
        validation_history = list(resume_state.validation_history)
        best_metric_value = resume_state.best_metric_value
        best_metric_name = resume_state.best_metric_name
        start_epoch = resume_state.epoch
        global_iteration = resume_state.global_iteration
    ema = YoloModelEMA(
        model=model,
        updates=resume_state.ema_updates if resume_state is not None else 0,
    )
    if resume_state is not None and resume_state.ema_state_dict is not None:
        ema.load_state_dict(resume_state.ema_state_dict, strict=False)

    try:
        loop_result = run_yolo11_classification_training_loop(
            imports=imports,
            model=model,
            optimizer=runtime.optimizer,
            scheduler=runtime.scheduler,
            scaler=runtime.scaler,
            autocast_context=runtime.autocast_context,
            labels=labels,
            train_annotations=train_annotations,
            val_annotations=val_annotations,
            batch_size=batch_size,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            checkpoint_interval=read_training_checkpoint_interval(extra),
            input_size=input_size,
            precision=precision,
            device_name=device_name,
            augmentation_options=augmentation_options,
            dataloader_plan=dataloader_plan,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            min_lr_ratio=min_lr_ratio,
            start_epoch=start_epoch,
            global_iteration=global_iteration,
            metrics_history=metrics_history,
            validation_history=validation_history,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            training_schedule=runtime.training_schedule,
            ema=ema,
            grad_clip_norm=float(extra.get("grad_clip_norm", 10.0)),
            epoch_callback=request.epoch_callback,
            batch_callback=request.batch_callback,
            savepoint_callback=request.savepoint_callback,
            control_callback=request.control_callback,
        )
    except CoreYolo11ClassificationTrainingTerminatedError as exc:
        raise Yolo11ClassificationTrainingTerminatedError() from exc
    except CoreYolo11ClassificationTrainingPausedError as exc:
        raise Yolo11ClassificationTrainingPausedError() from exc

    final_val_metrics = (
        loop_result.validation_history[-1] if loop_result.validation_history else {}
    )
    best_checkpoint_bytes = loop_result.best_checkpoint_bytes
    if (
        best_checkpoint_bytes is None
        and request.previous_best_checkpoint_path is not None
        and request.previous_best_checkpoint_path.is_file()
    ):
        best_checkpoint_bytes = request.previous_best_checkpoint_path.read_bytes()
    if best_checkpoint_bytes is None:
        best_checkpoint_bytes = loop_result.latest_checkpoint_bytes
    test_metrics_payload = build_unavailable_test_metrics_report(
        reason="dataset export 未提供独立 test split"
    )
    if test_annotations:
        checkpoint_payload = imports.torch.load(
            io.BytesIO(best_checkpoint_bytes),
            map_location="cpu",
            weights_only=False,
        )
        ema_state_dict = (
            checkpoint_payload.get("ema_state_dict")
            if isinstance(checkpoint_payload, dict)
            else None
        )
        if not isinstance(ema_state_dict, dict):
            raise InvalidRequestError(
                "YOLO11 classification best checkpoint 缺少 ema_state_dict"
            )
        load_yolo11_classification_model_state(
            model=ema.model,
            state_dict=ema_state_dict,
            device_name=device_name,
        )
        test_metrics_payload = evaluate_yolo11_classification_samples(
            model=ema.model,
            samples=test_annotations,
            labels=labels,
            batch_size=batch_size,
            input_size=input_size,
            device=device_name,
            precision=precision,
            imports=imports,
            dataloader_plan=dataloader_plan,
            include_details=True,
            split_name="test",
            checkpoint_role="best",
            control_callback=request.control_callback,
        )
    return Yolo11ClassificationTrainingExecutionResult(
        best_metric_value=loop_result.best_metric_value,
        best_metric_name=loop_result.best_metric_name,
        latest_checkpoint_bytes=loop_result.latest_checkpoint_bytes,
        metrics_payload={
            "final_metrics": (
                {
                    "loss": loop_result.metrics_history[-1].get("loss", 0.0),
                    "accuracy": loop_result.metrics_history[-1].get("accuracy", 0.0),
                }
                if loop_result.metrics_history
                else {}
            ),
            "epoch_history": loop_result.metrics_history,
            "scheduler": "LambdaLR",
            "optimizer": runtime.training_schedule.optimizer_name,
            "initial_learning_rate": runtime.training_schedule.initial_lr,
            "final_learning_rate": resolve_yolo_optimizer_base_learning_rate(
                optimizer=runtime.optimizer,
                initial_learning_rate=runtime.training_schedule.initial_lr,
            ),
            "accumulate": runtime.training_schedule.accumulate,
            "scaled_weight_decay": runtime.training_schedule.scaled_weight_decay,
            "implementation_mode": YOLO11_CLASSIFICATION_IMPLEMENTATION_MODE,
            "augmentation": build_yolo_classification_augmentation_summary(
                augmentation_options
            ),
        },
        validation_metrics_payload={
            "final_metrics": final_val_metrics,
            "epoch_history": loop_result.validation_history,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
        best_checkpoint_bytes=best_checkpoint_bytes,
        test_metrics_payload=test_metrics_payload,
    )


__all__ = [
    "YOLO11_CLASSIFICATION_IMPLEMENTATION_MODE",
    "Yolo11ClassificationTrainingControlCommand",
    "Yolo11ClassificationTrainingEpochProgress",
    "Yolo11ClassificationTrainingExecutionRequest",
    "Yolo11ClassificationTrainingExecutionResult",
    "Yolo11ClassificationTrainingPausedError",
    "Yolo11ClassificationTrainingSavePoint",
    "Yolo11ClassificationTrainingTerminatedError",
    "run_yolo11_classification_training",
]
