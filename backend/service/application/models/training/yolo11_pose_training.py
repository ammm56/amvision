"""YOLO11 pose 专属训练执行入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo11_core import build_yolo11_model
from backend.service.application.models.yolo11_core.data import (
    build_yolo11_task_augmentation_options,
)
from backend.service.application.models.yolo11_core.training.pose_checkpoint import (
    load_yolo11_pose_resume_state,
    restore_yolo11_pose_training_state,
    validate_yolo11_pose_resume_parameters,
)
from backend.service.application.models.yolo11_core.training.pose_imports import (
    build_yolo11_pose_autocast_context,
    require_yolo11_pose_training_imports,
    resolve_yolo11_pose_training_device,
)
from backend.service.application.models.yolo11_core.training.pose_manifest import (
    load_yolo11_pose_training_manifest,
)
from backend.service.application.models.yolo11_core.training.pose_trainer import (
    Yolo11PoseTrainingControlCommand,
    Yolo11PoseTrainingEpochProgress,
    Yolo11PoseTrainingPausedError,
    Yolo11PoseTrainingSavePoint,
    Yolo11PoseTrainingTerminatedError,
    run_yolo11_pose_training_loop,
)
from backend.service.application.models.yolo11_core.weights import (
    load_yolo11_checkpoint_file,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO11_POSE_IMPLEMENTATION_MODE = "yolo11-pose-core"
YOLO11_POSE_DEFAULT_INPUT_SIZE = (640, 640)
YOLO11_POSE_DEFAULT_BATCH_SIZE = 1
YOLO11_POSE_DEFAULT_MAX_EPOCHS = 1
YOLO11_POSE_DEFAULT_EVAL_INTERVAL = 5
YOLO11_POSE_DEFAULT_LR = 1e-3
YOLO11_POSE_DEFAULT_WEIGHT_DECAY = 1e-4
YOLO11_POSE_DEFAULT_MIN_LR_RATIO = 0.01
YOLO11_POSE_DEFAULT_CLASS_LOSS = 0.5
YOLO11_POSE_DEFAULT_BOX_LOSS = 7.5
YOLO11_POSE_DEFAULT_DFL_LOSS = 1.5
YOLO11_POSE_DEFAULT_KPT_LOSS = 12.0
YOLO11_POSE_DEFAULT_ASSIGN_TOPK = 10
YOLO11_POSE_DEFAULT_ASSIGN_ALPHA = 0.5
YOLO11_POSE_DEFAULT_ASSIGN_BETA = 6.0
YOLO11_POSE_DEFAULT_GRAD_CLIP = 10.0
YOLO11_POSE_DEFAULT_EVAL_CONF = 0.01
YOLO11_POSE_DEFAULT_EVAL_NMS = 0.65
YOLO11_POSE_DEFAULT_KPT_CONF = 0.25


@dataclass(frozen=True)
class Yolo11PoseTrainingExecutionRequest:
    """描述一次 YOLO11 pose 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = YOLO11_POSE_DEFAULT_BATCH_SIZE
    max_epochs: int = YOLO11_POSE_DEFAULT_MAX_EPOCHS
    evaluation_interval: int = YOLO11_POSE_DEFAULT_EVAL_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: (
        Callable[
            [Yolo11PoseTrainingEpochProgress],
            Yolo11PoseTrainingControlCommand | None,
        ]
        | None
    ) = None
    savepoint_callback: Callable[[Yolo11PoseTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class Yolo11PoseTrainingExecutionResult:
    """描述一次 YOLO11 pose 训练执行结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    warm_start_summary: dict[str, object]


def run_yolo11_pose_training(
    request: Yolo11PoseTrainingExecutionRequest,
) -> Yolo11PoseTrainingExecutionResult:
    """执行一次 YOLO11 pose 训练。"""

    if request.model_type != "yolo11":
        raise InvalidRequestError(
            "YOLO11 pose 训练入口只接受 model_type=yolo11",
            details={"model_type": request.model_type},
        )

    imports = require_yolo11_pose_training_imports()
    device_name = resolve_yolo11_pose_training_device(
        torch_module=imports.torch,
        extra_options=request.extra_options,
    )
    precision = request.precision
    input_size = request.input_size or YOLO11_POSE_DEFAULT_INPUT_SIZE
    manifest = load_yolo11_pose_training_manifest(
        dataset_storage=request.dataset_storage,
        manifest_payload=request.manifest_payload,
    )
    labels = manifest.labels
    kpt_shape = manifest.keypoint_shape
    model = build_yolo11_model(
        task_type=POSE_TASK_TYPE,
        model_scale=request.model_scale,
        num_classes=len(labels),
        model_config_overrides={"kpt_shape": kpt_shape},
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
        resume_state = load_yolo11_pose_resume_state(
            checkpoint_path=request.resume_checkpoint_path,
            torch_module=imports.torch,
        )

    extra = dict(request.extra_options or {})
    learning_rate = float(extra.get("learning_rate", YOLO11_POSE_DEFAULT_LR))
    weight_decay = float(extra.get("weight_decay", YOLO11_POSE_DEFAULT_WEIGHT_DECAY))
    min_lr_ratio = float(extra.get("min_lr_ratio", YOLO11_POSE_DEFAULT_MIN_LR_RATIO))
    batch_size = max(1, int(extra.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra.get("max_epochs", request.max_epochs)))
    evaluation_interval = max(
        1,
        int(extra.get("evaluation_interval", request.evaluation_interval)),
    )
    class_loss_weight = float(
        extra.get("class_loss_weight", YOLO11_POSE_DEFAULT_CLASS_LOSS)
    )
    box_loss_weight = float(extra.get("box_loss_weight", YOLO11_POSE_DEFAULT_BOX_LOSS))
    dfl_loss_weight = float(extra.get("dfl_loss_weight", YOLO11_POSE_DEFAULT_DFL_LOSS))
    kpt_loss_weight = float(extra.get("kpt_loss_weight", YOLO11_POSE_DEFAULT_KPT_LOSS))
    assign_topk = max(1, int(extra.get("assign_topk", YOLO11_POSE_DEFAULT_ASSIGN_TOPK)))
    assign_alpha = float(extra.get("assign_alpha", YOLO11_POSE_DEFAULT_ASSIGN_ALPHA))
    assign_beta = float(extra.get("assign_beta", YOLO11_POSE_DEFAULT_ASSIGN_BETA))
    assign_topk2 = int(extra["assign_topk2"]) if "assign_topk2" in extra else None
    grad_clip_norm = max(
        0.0, float(extra.get("grad_clip_norm", YOLO11_POSE_DEFAULT_GRAD_CLIP))
    )
    eval_conf = float(
        extra.get("eval_confidence_threshold", YOLO11_POSE_DEFAULT_EVAL_CONF)
    )
    eval_nms = float(extra.get("eval_nms_threshold", YOLO11_POSE_DEFAULT_EVAL_NMS))
    keypoint_conf = float(
        extra.get("keypoint_confidence_threshold", YOLO11_POSE_DEFAULT_KPT_CONF)
    )
    augmentation_options = build_yolo11_task_augmentation_options(extra)

    if resume_state is not None:
        validate_yolo11_pose_resume_parameters(
            resume_state,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
            class_loss_weight=class_loss_weight,
            box_loss_weight=box_loss_weight,
            dfl_loss_weight=dfl_loss_weight,
            kpt_loss_weight=kpt_loss_weight,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            grad_clip_norm=grad_clip_norm,
            evaluation_confidence_threshold=eval_conf,
            evaluation_nms_threshold=eval_nms,
            keypoint_confidence_threshold=keypoint_conf,
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
        restore_yolo11_pose_training_state(
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

    loop_result = run_yolo11_pose_training_loop(
        imports=imports,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        trainable_parameters=trainable_parameters,
        autocast_context=lambda: build_yolo11_pose_autocast_context(
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
        kpt_shape=kpt_shape,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        kpt_loss_weight=kpt_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
        assign_topk2=assign_topk2,
        grad_clip_norm=grad_clip_norm,
        evaluation_confidence_threshold=eval_conf,
        evaluation_nms_threshold=eval_nms,
        keypoint_confidence_threshold=keypoint_conf,
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
    return Yolo11PoseTrainingExecutionResult(
        best_metric_value=loop_result.best_metric_value,
        best_metric_name=loop_result.best_metric_name,
        latest_checkpoint_bytes=loop_result.latest_checkpoint_bytes,
        metrics_payload={
            "final_metrics": loop_result.metrics_history[-1]
            if loop_result.metrics_history
            else {},
            "epoch_history": loop_result.metrics_history,
            "kpt_shape": list(kpt_shape),
            "implementation_mode": YOLO11_POSE_IMPLEMENTATION_MODE,
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
    "YOLO11_POSE_IMPLEMENTATION_MODE",
    "Yolo11PoseTrainingControlCommand",
    "Yolo11PoseTrainingEpochProgress",
    "Yolo11PoseTrainingExecutionRequest",
    "Yolo11PoseTrainingExecutionResult",
    "Yolo11PoseTrainingPausedError",
    "Yolo11PoseTrainingSavePoint",
    "Yolo11PoseTrainingTerminatedError",
    "run_yolo11_pose_training",
]
