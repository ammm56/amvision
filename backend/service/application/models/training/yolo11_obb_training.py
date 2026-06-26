"""YOLO11 OBB 专属训练执行入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo11_core import build_yolo11_model
from backend.service.application.models.yolo11_core.data import (
    build_yolo11_task_augmentation_options,
)
from backend.service.application.models.yolo11_core.training.obb_checkpoint import (
    load_yolo11_obb_resume_state,
    restore_yolo11_obb_training_state,
    validate_yolo11_obb_resume_parameters,
)
from backend.service.application.models.yolo11_core.training.obb_imports import (
    build_yolo11_obb_autocast_context,
    require_yolo11_obb_training_imports,
    resolve_yolo11_obb_training_device,
)
from backend.service.application.models.yolo11_core.training.obb_manifest import (
    load_yolo11_obb_training_manifest,
)
from backend.service.application.models.yolo11_core.training.obb_trainer import (
    Yolo11ObbTrainingControlCommand,
    Yolo11ObbTrainingEpochProgress,
    Yolo11ObbTrainingPausedError,
    Yolo11ObbTrainingSavePoint,
    Yolo11ObbTrainingTerminatedError,
    run_yolo11_obb_training_loop,
)
from backend.service.application.models.yolo11_core.weights import (
    load_yolo11_checkpoint_file,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO11_OBB_IMPLEMENTATION_MODE = "yolo11-obb-core"
YOLO11_OBB_DEFAULT_INPUT_SIZE = (640, 640)
YOLO11_OBB_DEFAULT_BATCH_SIZE = 1
YOLO11_OBB_DEFAULT_MAX_EPOCHS = 1
YOLO11_OBB_DEFAULT_EVAL_INTERVAL = 5
YOLO11_OBB_DEFAULT_LR = 1e-3
YOLO11_OBB_DEFAULT_WEIGHT_DECAY = 1e-4
YOLO11_OBB_DEFAULT_MIN_LR_RATIO = 0.01
YOLO11_OBB_DEFAULT_EVAL_CONF = 0.01
YOLO11_OBB_DEFAULT_EVAL_NMS = 0.7


@dataclass(frozen=True)
class Yolo11ObbTrainingExecutionRequest:
    """描述一次 YOLO11 OBB 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = YOLO11_OBB_DEFAULT_BATCH_SIZE
    max_epochs: int = YOLO11_OBB_DEFAULT_MAX_EPOCHS
    evaluation_interval: int = YOLO11_OBB_DEFAULT_EVAL_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: (
        Callable[
            [Yolo11ObbTrainingEpochProgress],
            Yolo11ObbTrainingControlCommand | None,
        ]
        | None
    ) = None
    savepoint_callback: Callable[[Yolo11ObbTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class Yolo11ObbTrainingExecutionResult:
    """描述一次 YOLO11 OBB 训练执行结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    warm_start_summary: dict[str, object]


def run_yolo11_obb_training(
    request: Yolo11ObbTrainingExecutionRequest,
) -> Yolo11ObbTrainingExecutionResult:
    """执行一次 YOLO11 OBB 训练。"""

    if request.model_type != "yolo11":
        raise InvalidRequestError(
            "YOLO11 OBB 训练入口只接受 model_type=yolo11",
            details={"model_type": request.model_type},
        )

    imports = require_yolo11_obb_training_imports()
    device_name = resolve_yolo11_obb_training_device(
        torch_module=imports.torch,
        extra_options=request.extra_options,
    )
    precision = request.precision
    input_size = request.input_size or YOLO11_OBB_DEFAULT_INPUT_SIZE
    manifest = load_yolo11_obb_training_manifest(
        dataset_storage=request.dataset_storage,
        manifest_payload=request.manifest_payload,
    )
    labels = manifest.labels
    model = build_yolo11_model(
        task_type=OBB_TASK_TYPE,
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
        resume_state = load_yolo11_obb_resume_state(
            checkpoint_path=request.resume_checkpoint_path,
            torch_module=imports.torch,
        )

    extra = dict(request.extra_options or {})
    learning_rate = float(extra.get("learning_rate", YOLO11_OBB_DEFAULT_LR))
    weight_decay = float(extra.get("weight_decay", YOLO11_OBB_DEFAULT_WEIGHT_DECAY))
    min_lr_ratio = float(extra.get("min_lr_ratio", YOLO11_OBB_DEFAULT_MIN_LR_RATIO))
    batch_size = max(1, int(extra.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra.get("max_epochs", request.max_epochs)))
    evaluation_interval = max(
        1,
        int(extra.get("evaluation_interval", request.evaluation_interval)),
    )
    assign_topk2 = int(extra["assign_topk2"]) if "assign_topk2" in extra else None
    eval_conf = float(
        extra.get("evaluation_confidence_threshold", YOLO11_OBB_DEFAULT_EVAL_CONF)
    )
    eval_nms = float(
        extra.get("evaluation_nms_threshold", YOLO11_OBB_DEFAULT_EVAL_NMS)
    )
    augmentation_options = build_yolo11_task_augmentation_options(extra)

    if resume_state is not None:
        validate_yolo11_obb_resume_parameters(
            resume_state,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
            evaluation_confidence_threshold=eval_conf,
            evaluation_nms_threshold=eval_nms,
        )

    model.to(device_name)
    trainable_parameters = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]
    optimizer = imports.torch.optim.AdamW(
        trainable_parameters,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    iterations_per_epoch = max(
        1,
        (len(manifest.train_annotations) + batch_size - 1) // batch_size,
    )
    scheduler = imports.torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max_epochs * iterations_per_epoch,
        eta_min=learning_rate * min_lr_ratio,
    )
    scaler = (
        imports.torch.amp.GradScaler("cuda", enabled=True)
        if precision == "fp16" and "cuda" in device_name
        else None
    )

    start_epoch = 0
    global_iteration = 0
    metrics_history: list[dict[str, float]] = []
    validation_history: list[dict[str, float]] = []
    best_metric_value = 0.0
    best_metric_name = "val_map50_95"
    if resume_state is not None:
        restore_yolo11_obb_training_state(
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            state=resume_state,
            device_name=device_name,
        )
        metrics_history = list(resume_state.metrics_history)
        validation_history = list(resume_state.validation_history)
        best_metric_value = resume_state.best_metric_value
        best_metric_name = resume_state.best_metric_name
        start_epoch = resume_state.epoch
        global_iteration = resume_state.global_iteration

    loop_result = run_yolo11_obb_training_loop(
        imports=imports,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        trainable_parameters=trainable_parameters,
        autocast_context=lambda: build_yolo11_obb_autocast_context(
            torch_module=imports.torch,
            precision=precision,
            device_name=device_name,
        ),
        labels=labels,
        train_annotations=manifest.train_annotations,
        val_annotations=manifest.val_annotations,
        batch_size=batch_size,
        max_epochs=max_epochs,
        evaluation_interval=evaluation_interval,
        input_size=input_size,
        precision=precision,
        device_name=device_name,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        min_lr_ratio=min_lr_ratio,
        assign_topk2=assign_topk2,
        evaluation_confidence_threshold=eval_conf,
        evaluation_nms_threshold=eval_nms,
        augmentation_options=augmentation_options,
        start_epoch=start_epoch,
        global_iteration=global_iteration,
        metrics_history=metrics_history,
        validation_history=validation_history,
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        epoch_callback=request.epoch_callback,
        savepoint_callback=request.savepoint_callback,
    )
    return Yolo11ObbTrainingExecutionResult(
        best_metric_value=loop_result.best_metric_value,
        best_metric_name=loop_result.best_metric_name,
        latest_checkpoint_bytes=loop_result.latest_checkpoint_bytes,
        metrics_payload={
            "final_metrics": loop_result.metrics_history[-1]
            if loop_result.metrics_history
            else {},
            "epoch_history": loop_result.metrics_history,
            "implementation_mode": YOLO11_OBB_IMPLEMENTATION_MODE,
        },
        validation_metrics_payload={
            "final_metrics": loop_result.validation_history[-1]
            if loop_result.validation_history
            else {},
            "epoch_history": loop_result.validation_history,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
    )


__all__ = [
    "YOLO11_OBB_IMPLEMENTATION_MODE",
    "Yolo11ObbTrainingControlCommand",
    "Yolo11ObbTrainingEpochProgress",
    "Yolo11ObbTrainingExecutionRequest",
    "Yolo11ObbTrainingExecutionResult",
    "Yolo11ObbTrainingPausedError",
    "Yolo11ObbTrainingSavePoint",
    "Yolo11ObbTrainingTerminatedError",
    "run_yolo11_obb_training",
]
