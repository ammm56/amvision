"""YOLO26 OBB 专属训练执行入口。"""

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
from backend.service.application.models.training.detection_evaluation_report import (
    build_detection_test_metrics_report,
)
from backend.service.application.models.yolo26_core import build_yolo26_model
from backend.service.application.models.yolo26_core.data import (
    build_yolo26_task_augmentation_options,
)
from backend.service.application.models.yolo26_core.evaluation import (
    evaluate_yolo26_obb_samples,
)
from backend.service.application.models.yolo26_core.training.obb_checkpoint import (
    load_yolo26_obb_resume_state,
    restore_yolo26_obb_training_state,
    validate_yolo26_obb_resume_parameters,
)
from backend.service.application.models.yolo26_core.training.obb_imports import (
    build_yolo26_obb_autocast_context,
    require_yolo26_obb_training_imports,
    resolve_yolo26_obb_training_device,
)
from backend.service.application.models.yolo26_core.training.obb_manifest import (
    load_yolo26_obb_training_manifest,
)
from backend.service.application.models.yolo26_core.training.obb_trainer import (
    Yolo26ObbTrainingControlCommand,
    Yolo26ObbTrainingEpochProgress,
    Yolo26ObbTrainingPausedError,
    Yolo26ObbTrainingSavePoint,
    Yolo26ObbTrainingTerminatedError,
    run_yolo26_obb_training_loop,
)
from backend.service.application.models.yolo26_core.weights import (
    load_yolo26_checkpoint_file,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloModelEMA,
    YoloTaskTrainingBatchProgress,
    build_yolo_ultralytics_optimizer,
    build_yolo_ultralytics_scheduler,
    resolve_yolo_optimizer_base_learning_rate,
    resolve_yolo_task_dataloader_plan,
)
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO26_OBB_IMPLEMENTATION_MODE = "yolo26-obb-core"
YOLO26_OBB_DEFAULT_INPUT_SIZE = (640, 640)
YOLO26_OBB_DEFAULT_BATCH_SIZE = 1
YOLO26_OBB_DEFAULT_MAX_EPOCHS = 1
YOLO26_OBB_DEFAULT_EVAL_INTERVAL = 5
YOLO26_OBB_DEFAULT_LR = 1e-2
YOLO26_OBB_DEFAULT_WEIGHT_DECAY = 5e-4
YOLO26_OBB_DEFAULT_MIN_LR_RATIO = 0.01
YOLO26_OBB_DEFAULT_EVAL_CONF = 0.01


@dataclass(frozen=True)
class Yolo26ObbTrainingExecutionRequest:
    """描述一次 YOLO26 OBB 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = YOLO26_OBB_DEFAULT_BATCH_SIZE
    max_epochs: int = YOLO26_OBB_DEFAULT_MAX_EPOCHS
    evaluation_interval: int = YOLO26_OBB_DEFAULT_EVAL_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    previous_best_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: (
        Callable[
            [Yolo26ObbTrainingEpochProgress],
            Yolo26ObbTrainingControlCommand | None,
        ]
        | None
    ) = None
    batch_callback: Callable[[YoloTaskTrainingBatchProgress], None] | None = None
    control_callback: (
        Callable[[], Yolo26ObbTrainingControlCommand | None] | None
    ) = None
    savepoint_callback: Callable[[Yolo26ObbTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class Yolo26ObbTrainingExecutionResult:
    """描述一次 YOLO26 OBB 训练执行结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    warm_start_summary: dict[str, object]
    best_checkpoint_bytes: bytes | None = None
    test_metrics_payload: dict[str, object] | None = None
    test_split_name: str | None = None
    test_sample_count: int = 0


@training_engine_entrypoint
def run_yolo26_obb_training(
    request: Yolo26ObbTrainingExecutionRequest,
) -> Yolo26ObbTrainingExecutionResult:
    """执行一次 YOLO26 OBB 训练。"""

    if request.model_type != "yolo26":
        raise InvalidRequestError(
            "YOLO26 OBB 训练入口只接受 model_type=yolo26",
            details={"model_type": request.model_type},
        )

    imports = require_yolo26_obb_training_imports()
    device_name = resolve_yolo26_obb_training_device(
        torch_module=imports.torch,
        extra_options=request.extra_options,
    )
    precision = resolve_training_amp_runtime(
        torch_module=imports.torch,
        device_name=device_name,
        requested_precision=request.precision,
        extra_options=request.extra_options,
    ).precision
    input_size = request.input_size or YOLO26_OBB_DEFAULT_INPUT_SIZE
    manifest = load_yolo26_obb_training_manifest(
        dataset_storage=request.dataset_storage,
        manifest_payload=request.manifest_payload,
    )
    labels = manifest.labels
    model = build_yolo26_model(
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
        load_result = load_yolo26_checkpoint_file(
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
        resume_state = load_yolo26_obb_resume_state(
            checkpoint_path=request.resume_checkpoint_path,
            torch_module=imports.torch,
        )

    extra = dict(request.extra_options or {})
    learning_rate = float(extra.get("learning_rate", YOLO26_OBB_DEFAULT_LR))
    weight_decay = float(extra.get("weight_decay", YOLO26_OBB_DEFAULT_WEIGHT_DECAY))
    min_lr_ratio = float(extra.get("min_lr_ratio", YOLO26_OBB_DEFAULT_MIN_LR_RATIO))
    batch_size = max(1, int(extra.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra.get("max_epochs", request.max_epochs)))
    evaluation_interval = max(
        1,
        int(extra.get("evaluation_interval", request.evaluation_interval)),
    )
    assign_topk2 = int(extra["assign_topk2"]) if "assign_topk2" in extra else None
    eval_conf = float(
        extra.get("evaluation_confidence_threshold", YOLO26_OBB_DEFAULT_EVAL_CONF)
    )
    augmentation_options = build_yolo26_task_augmentation_options(extra)

    model.to(device_name)
    batch_size = resolve_training_batch_size(
        torch_module=imports.torch,
        model=model,
        device_name=device_name,
        input_size=input_size,
        dataset_size=len(manifest.train_annotations),
        requested_batch_size=request.batch_size,
        default_batch_size=YOLO26_OBB_DEFAULT_BATCH_SIZE,
        runtime_precision=precision,
        extra_options=extra,
        resume_batch_size=read_resume_checkpoint_batch_size(
            torch_module=imports.torch,
            checkpoint_path=request.resume_checkpoint_path,
        ),
    ).batch_size
    if resume_state is not None:
        validate_yolo26_obb_resume_parameters(
            resume_state,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
            evaluation_confidence_threshold=eval_conf,
        )
    optimizer, training_schedule = build_yolo_ultralytics_optimizer(
        torch_module=imports.torch,
        model=model,
        num_classes=len(labels),
        batch_size=batch_size,
        train_sample_count=len(manifest.train_annotations),
        max_epochs=max_epochs,
        optimizer_name=str(extra.get("optimizer", "auto")),
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        final_lr_ratio=min_lr_ratio,
        cosine_schedule=bool(extra.get("cos_lr", False)),
    )
    scheduler = build_yolo_ultralytics_scheduler(
        torch_module=imports.torch,
        optimizer=optimizer,
        max_epochs=max_epochs,
        final_lr_ratio=min_lr_ratio,
        cosine_schedule=training_schedule.cosine_schedule,
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
    best_metric_value = -1.0
    best_metric_name = "val_map50_95"
    if resume_state is not None:
        restore_yolo26_obb_training_state(
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
    ema = YoloModelEMA(
        model=model,
        updates=resume_state.ema_updates if resume_state is not None else 0,
    )
    if resume_state is not None and resume_state.ema_state_dict is not None:
        ema.load_state_dict(resume_state.ema_state_dict, strict=False)

    loop_result = run_yolo26_obb_training_loop(
        imports=imports,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        training_schedule=training_schedule,
        ema=ema,
        autocast_context=lambda: build_yolo26_obb_autocast_context(
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
        checkpoint_interval=read_training_checkpoint_interval(extra),
        input_size=input_size,
        precision=precision,
        device_name=device_name,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        min_lr_ratio=min_lr_ratio,
        assign_topk2=assign_topk2,
        evaluation_confidence_threshold=eval_conf,
        augmentation_options=augmentation_options,
        start_epoch=start_epoch,
        global_iteration=global_iteration,
        metrics_history=metrics_history,
        validation_history=validation_history,
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        previous_best_checkpoint_bytes=(
            request.previous_best_checkpoint_path.read_bytes()
            if request.previous_best_checkpoint_path is not None
            and request.previous_best_checkpoint_path.is_file()
            else b""
        ),
        epoch_callback=request.epoch_callback,
        batch_callback=request.batch_callback,
        control_callback=request.control_callback,
        savepoint_callback=request.savepoint_callback,
        dataloader_plan=resolve_yolo_task_dataloader_plan(
            extra_options=extra,
            device=device_name,
        ),
    )
    test_metrics_payload = build_detection_test_metrics_report(
        available=False,
        sample_count=0,
        category_names=labels,
        reason="dataset export does not contain an independent test split",
        task_type="obb",
    )
    if manifest.test_annotations:
        checkpoint_payload = imports.torch.load(
            io.BytesIO(loop_result.best_checkpoint_bytes),
            map_location="cpu",
            weights_only=False,
        )
        best_state_dict = checkpoint_payload.get("ema_state_dict")
        if not isinstance(best_state_dict, dict):
            best_state_dict = checkpoint_payload.get("model_state_dict")
        if not isinstance(best_state_dict, dict):
            raise InvalidRequestError("YOLO26 OBB best checkpoint 缺少模型权重")
        ema.model.load_state_dict(best_state_dict, strict=False)
        ema.model.to(device_name)
        test_metrics = evaluate_yolo26_obb_samples(
            model=ema.model,
            samples=manifest.test_annotations,
            labels=labels,
            input_size=input_size,
            device=device_name,
            precision=precision,
            score_threshold=eval_conf,
            imports=imports,
            batch_size=batch_size,
            control_callback=request.control_callback,
        )
        test_metrics_payload = build_detection_test_metrics_report(
            available=True,
            sample_count=len(manifest.test_annotations),
            metrics=test_metrics,
            category_names=labels,
            task_type="obb",
        )
    return Yolo26ObbTrainingExecutionResult(
        best_metric_value=loop_result.best_metric_value,
        best_metric_name=loop_result.best_metric_name,
        latest_checkpoint_bytes=loop_result.latest_checkpoint_bytes,
        metrics_payload={
            "final_metrics": loop_result.metrics_history[-1]
            if loop_result.metrics_history
            else {},
            "epoch_history": loop_result.metrics_history,
            "optimizer": training_schedule.optimizer_name,
            "initial_learning_rate": training_schedule.initial_lr,
            "final_learning_rate": resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            "implementation_mode": YOLO26_OBB_IMPLEMENTATION_MODE,
        },
        validation_metrics_payload={
            "final_metrics": loop_result.validation_history[-1]
            if loop_result.validation_history
            else {},
            "epoch_history": loop_result.validation_history,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
        best_checkpoint_bytes=loop_result.best_checkpoint_bytes,
        test_metrics_payload=test_metrics_payload,
        test_split_name="test" if manifest.test_annotations else None,
        test_sample_count=len(manifest.test_annotations),
    )


__all__ = [
    "YOLO26_OBB_IMPLEMENTATION_MODE",
    "Yolo26ObbTrainingControlCommand",
    "Yolo26ObbTrainingEpochProgress",
    "Yolo26ObbTrainingExecutionRequest",
    "Yolo26ObbTrainingExecutionResult",
    "Yolo26ObbTrainingPausedError",
    "Yolo26ObbTrainingSavePoint",
    "Yolo26ObbTrainingTerminatedError",
    "run_yolo26_obb_training",
]
