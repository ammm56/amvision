"""YOLOv8 pose 训练执行入口。"""

from __future__ import annotations

import io
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.models.training.metric_policy import (
    is_better_training_metric,
)

from backend.contracts.datasets.dataset_formats import (
    COCO_KEYPOINTS_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.device_selection import (
    resolve_single_training_device_name,
)
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
    resolve_training_checkpoint_persistence_decision,
)
from backend.service.application.models.training.detection_evaluation_report import (
    build_detection_test_metrics_report,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloModelEMA,
    YoloTaskTrainingDataLoaderLifecycle,
    build_yolo_epoch_history_item,
    YoloUltralyticsOptimizerStep,
    build_yolo_ultralytics_optimizer,
    build_yolo_ultralytics_scheduler,
    build_yolo_task_training_dataloader,
    load_yolo_task_dataloader_imports,
    move_yolo_task_batch_to_device,
    resolve_yolo_optimizer_base_learning_rate,
    resolve_yolo_task_dataloader_plan,
    should_run_yolo_validation,
)
from backend.service.application.models.yolo_core_common.training.pose_topology import (
    prepare_pose_augmentation_options,
)
from backend.service.application.models.support.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_pose_split,
    normalize_yolo_category_names,
)
from backend.service.application.models.yolov8_core import build_yolov8_model
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_pose_training_batch,
    build_yolov8_task_augmentation_options,
    resolve_yolov8_task_augmentation_for_epoch,
    resolve_yolov8_task_batch_input_size,
)
from backend.service.application.models.yolov8_core.evaluation import (
    evaluate_yolov8_pose_samples,
)
from backend.service.application.models.yolov8_core.losses import (
    compute_yolov8_pose_loss,
)
from backend.service.application.models.yolov8_core.weights import (
    load_yolov8_checkpoint_file,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)

YOLOV8_POSE_IMPLEMENTATION_MODE = "yolov8-pose-core"
_POSE_DEF_INPUT_SIZE = (640, 640)
_POSE_DEF_BS = 4
_POSE_DEF_EPOCHS = 50
YOLOV8_POSE_DEFAULT_EVALUATION_INTERVAL = 5
_POSE_DEF_ASSIGN_TOPK = 10
_POSE_DEF_CLS_W = 0.5
_POSE_DEF_BOX_W = 7.5
_POSE_DEF_DFL_W = 1.5
_POSE_DEF_KPT_W = 12.0
_POSE_DEF_ASSIGN_A = 0.5
_POSE_DEF_ASSIGN_B = 6.0
_POSE_DEF_MIN_LR = 0.01
_POSE_DEF_GRAD_CLIP = 10.0
_POSE_DEF_KPT_SHAPE = (17, 3)


@dataclass(frozen=True)
class YoloV8PoseTrainingBatchProgress:
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
class YoloV8PoseTrainingEpochProgress:
    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float] | None = None
    best_metric_value: float | None = None
    best_metric_name: str | None = None


@dataclass(frozen=True)
class YoloV8PoseTrainingSavePoint:
    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float
    is_best: bool = False


@dataclass(frozen=True)
class YoloV8PoseTrainingControlCommand:
    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class YoloV8PoseTrainingPausedError(Exception):
    pass


class YoloV8PoseTrainingTerminatedError(Exception):
    pass


@dataclass(frozen=True)
class _PoseAnnotation:
    """单张图片的 Pose 标注。"""

    image_path: str
    boxes_xywh: list[list[float]]
    class_ids: list[int]
    keypoints: list[list[float]] | None = None  # 每个元素为 (K*3,) 扁平列表


@dataclass(frozen=True)
class YoloV8PoseTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = _POSE_DEF_BS
    max_epochs: int = _POSE_DEF_EPOCHS
    evaluation_interval: int = YOLOV8_POSE_DEFAULT_EVALUATION_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    previous_best_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable | None = None
    batch_callback: Callable[[YoloV8PoseTrainingBatchProgress], None] | None = None
    control_callback: Callable[
        [], YoloV8PoseTrainingControlCommand | None
    ] | None = None
    savepoint_callback: Callable | None = None


@dataclass(frozen=True)
class YoloV8PoseTrainingExecutionResult:
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
def run_yolov8_pose_training(
    request: YoloV8PoseTrainingExecutionRequest,
) -> YoloV8PoseTrainingExecutionResult:
    """执行一次 YOLOv8 pose 训练。"""

    if request.model_type != "yolov8":
        raise InvalidRequestError(
            "YOLOv8 pose 训练入口只接受 model_type=yolov8",
            details={"model_type": request.model_type},
        )

    import cv2
    import numpy as np
    import torch

    device = resolve_single_training_device_name(
        torch_module=torch,
        extra_options=request.extra_options,
    )

    precision = resolve_training_amp_runtime(
        torch_module=torch,
        device_name=device,
        requested_precision=request.precision,
        extra_options=request.extra_options,
    ).precision
    input_size = request.input_size or _POSE_DEF_INPUT_SIZE
    use_amp = precision in {"fp16", "bf16"} and device.startswith("cuda")

    labels, train_anns, val_anns, test_anns = _load_pose_manifest(
        request.dataset_storage, request.manifest_payload
    )
    num_classes = len(labels)
    kpt_shape = _resolve_pose_keypoint_shape_from_annotations(
        manifest=request.manifest_payload,
        train_annotations=train_anns,
        val_annotations=val_anns,
    )

    model = build_yolov8_model(
        task_type="pose",
        model_scale=request.model_scale,
        num_classes=num_classes,
        model_config_overrides={"kpt_shape": kpt_shape},
    )
    model.to(device)
    warm_start_summary = build_yolo_disabled_warm_start_summary()
    if (
        request.resume_checkpoint_path is None
        and request.warm_start_checkpoint_path is not None
        and request.warm_start_checkpoint_path.is_file()
    ):
        load_result = load_yolov8_checkpoint_file(
            torch_module=torch,
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
    extra = prepare_pose_augmentation_options(
        extra_options=request.extra_options,
        manifest_payload=request.manifest_payload,
        keypoint_shape=kpt_shape,
    )
    lr = float(extra.get("learning_rate", 1e-2))
    weight_decay = float(extra.get("weight_decay", 5e-4))
    min_lr = float(extra.get("min_lr_ratio", _POSE_DEF_MIN_LR))
    bs = max(1, int(extra.get("batch_size", request.batch_size)))
    bs = resolve_training_batch_size(
        torch_module=torch,
        model=model,
        device_name=device,
        input_size=input_size,
        dataset_size=len(train_anns),
        requested_batch_size=request.batch_size,
        default_batch_size=_POSE_DEF_BS,
        runtime_precision=precision,
        extra_options=extra,
        resume_batch_size=read_resume_checkpoint_batch_size(
            torch_module=torch,
            checkpoint_path=request.resume_checkpoint_path,
        ),
    ).batch_size
    max_epochs = max(1, int(extra.get("max_epochs", request.max_epochs)))
    cls_w = float(extra.get("class_loss_weight", _POSE_DEF_CLS_W))
    box_w = float(extra.get("box_loss_weight", _POSE_DEF_BOX_W))
    dfl_w = float(extra.get("dfl_loss_weight", _POSE_DEF_DFL_W))
    kpt_w = float(extra.get("kpt_loss_weight", _POSE_DEF_KPT_W))
    assign_topk = max(1, int(extra.get("assign_topk", _POSE_DEF_ASSIGN_TOPK)))
    assign_alpha = float(extra.get("assign_alpha", _POSE_DEF_ASSIGN_A))
    assign_beta = float(extra.get("assign_beta", _POSE_DEF_ASSIGN_B))
    grad_clip = max(0.0, float(extra.get("grad_clip_norm", _POSE_DEF_GRAD_CLIP)))
    yolov8_augmentation_options = build_yolov8_task_augmentation_options(extra)

    optimizer, training_schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=model,
        num_classes=num_classes,
        batch_size=bs,
        train_sample_count=len(train_anns),
        max_epochs=max_epochs,
        optimizer_name=str(extra.get("optimizer", "auto")),
        learning_rate=lr,
        weight_decay=weight_decay,
        final_lr_ratio=min_lr,
        cosine_schedule=bool(extra.get("cos_lr", False)),
    )
    scheduler = build_yolo_ultralytics_scheduler(
        torch_module=torch,
        optimizer=optimizer,
        max_epochs=max_epochs,
        final_lr_ratio=min_lr,
        cosine_schedule=training_schedule.cosine_schedule,
    )
    scaler = (
        torch.amp.GradScaler("cuda", enabled=True)
        if precision == "fp16" and device.startswith("cuda")
        else None
    )

    # 恢复训练
    start_epoch = 0
    global_iteration = 0
    metrics_history: list[dict[str, object]] = []
    resume_payload: dict[str, object] | None = None
    if request.resume_checkpoint_path and request.resume_checkpoint_path.is_file():
        ckpt = torch.load(
            str(request.resume_checkpoint_path), map_location=device, weights_only=False
        )
        resume_payload = ckpt
        model.load_state_dict(ckpt["model_state_dict"], strict=False)
        if "optimizer_state_dict" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        if "scheduler_state_dict" in ckpt and ckpt["scheduler_state_dict"] is not None:
            scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        if scaler is not None and ckpt.get("scaler_state_dict") is not None:
            scaler.load_state_dict(ckpt["scaler_state_dict"])
        start_epoch = int(ckpt.get("epoch", 0))
        global_iteration = int(ckpt.get("global_iteration", 0))
        metrics_history = list(ckpt.get("metrics_history", []))

    best_metric_value = float(
        resume_payload.get("best_metric_value", -1.0) if resume_payload else -1.0
    )
    best_metric_name = str(
        resume_payload.get("best_metric_name", "val_oks_ap50_95")
        if resume_payload
        else "val_oks_ap50_95"
    )
    best_checkpoint_bytes = (
        request.previous_best_checkpoint_path.read_bytes()
        if request.previous_best_checkpoint_path is not None
        and request.previous_best_checkpoint_path.is_file()
        else b""
    )
    validation_history: list[dict[str, object]] = list(
        resume_payload.get("validation_history", []) if resume_payload else []
    )
    ema = YoloModelEMA(
        model=model,
        updates=int(resume_payload.get("ema_updates", 0)) if resume_payload else 0,
    )
    if resume_payload and isinstance(resume_payload.get("ema_state_dict"), dict):
        ema.load_state_dict(resume_payload["ema_state_dict"], strict=False)
    optimizer_step = YoloUltralyticsOptimizerStep(
        torch_module=torch,
        model=model,
        optimizer=optimizer,
        scaler=scaler,
        schedule=training_schedule,
        ema=ema,
        grad_clip_norm=grad_clip,
        initial_iteration=global_iteration,
    )

    def build_completed_epoch_checkpoint(completed_epoch: int) -> bytes:
        """序列化最近完整 epoch；仅保存在当前 Attempt 内存中。"""

        buffer = io.BytesIO()
        torch.save(
            {
                "epoch": completed_epoch,
                "global_iteration": global_iteration,
                "model_state_dict": model.state_dict(),
                "ema_state_dict": ema.state_dict(),
                "ema_updates": ema.updates,
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "scaler_state_dict": (
                    scaler.state_dict() if scaler is not None else None
                ),
                "metrics_history": metrics_history,
                "validation_history": validation_history,
                "best_metric_value": best_metric_value,
                "best_metric_name": best_metric_name,
                "batch_size": bs,
                "max_epochs": max_epochs,
                "evaluation_interval": request.evaluation_interval,
                "input_size": input_size,
                "precision": precision,
            },
            buffer,
        )
        return buffer.getvalue()

    ckpt_bytes = build_completed_epoch_checkpoint(start_epoch)
    last_completed_savepoint = YoloV8PoseTrainingSavePoint(
        latest_checkpoint_bytes=ckpt_bytes,
        train_metrics=dict(metrics_history[-1]) if metrics_history else {},
        validation_metrics=(
            dict(validation_history[-1]) if validation_history else {}
        ),
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        epoch=start_epoch,
        learning_rate=resolve_yolo_optimizer_base_learning_rate(
            optimizer=optimizer,
            initial_learning_rate=training_schedule.initial_lr,
        ),
    )

    def observe_control() -> None:
        """在 batch 安全点使用最近完整 epoch 快照执行控制。"""

        if request.control_callback is None:
            return
        command = request.control_callback()
        if command is None:
            return
        if (
            command.save_checkpoint
            or command.pause_training
            or command.terminate_training
        ) and request.savepoint_callback is not None:
            request.savepoint_callback(last_completed_savepoint)
        if command.pause_training:
            raise YoloV8PoseTrainingPausedError()
        if command.terminate_training:
            raise YoloV8PoseTrainingTerminatedError()
    dataloader_plan = resolve_yolo_task_dataloader_plan(
        extra_options=dict(request.extra_options or {}),
        device=device,
    )

    training_loader_lifecycle = YoloTaskTrainingDataLoaderLifecycle()
    for epoch in range(start_epoch, max_epochs):
        model.train()
        epoch_losses: dict[str, float] = {}
        epoch_iters = 0
        epoch_samples = 0
        effective_yolov8_augmentation_options = (
            resolve_yolov8_task_augmentation_for_epoch(
                augmentation_options=yolov8_augmentation_options,
                epoch_index=epoch,
                max_epochs=max_epochs,
            )
        )

        train_dataloader = training_loader_lifecycle.resolve(
            augmentation_options=effective_yolov8_augmentation_options,
            build_loader=lambda: build_yolo_task_training_dataloader(
                torch_module=torch,
                samples=train_anns,
                batch_size=bs,
                input_size=input_size,
                training=True,
                augmentation_options=effective_yolov8_augmentation_options,
                plan=dataloader_plan,
                shuffle=True,
                build_batch=build_yolov8_pose_training_batch,
                load_imports=load_yolo_task_dataloader_imports,
                resolve_batch_input_size=resolve_yolov8_task_batch_input_size,
            ),
        )
        max_iterations = max(1, len(train_dataloader))
        for iteration, cpu_batch in enumerate(train_dataloader, start=1):
            observe_control()
            if cpu_batch is None:
                continue
            batch = move_yolo_task_batch_to_device(
                batch=cpu_batch,
                device=device,
                precision=precision,
                torch_module=torch,
            )
            if batch is None:
                continue
            images = batch.images
            targets = batch.targets
            global_iteration += 1
            optimizer_step.prepare_batch(
                iteration_index=global_iteration,
                epoch=epoch + 1,
                batch_size=len(targets),
            )

            autocast_ctx = (
                torch.amp.autocast(
                    "cuda",
                    dtype=(torch.float16 if precision == "fp16" else torch.bfloat16),
                    enabled=True,
                )
                if use_amp
                else nullcontext()
            )
            with autocast_ctx:
                raw_outputs = model(images)
                if isinstance(raw_outputs, dict) and "one2many" in raw_outputs:
                    raw_for_loss = raw_outputs["one2many"]
                else:
                    raw_for_loss = raw_outputs

                loss_dict = compute_yolov8_pose_loss(
                    torch=torch,
                    model=model,
                    raw_outputs=raw_for_loss,
                    batch_targets=targets,
                    num_classes=num_classes,
                    kpt_shape=kpt_shape,
                    class_loss_weight=cls_w,
                    box_loss_weight=box_w,
                    dfl_loss_weight=dfl_w,
                    kpt_loss_weight=kpt_w,
                    assign_topk=assign_topk,
                    assign_alpha=assign_alpha,
                    assign_beta=assign_beta,
                )

            total_loss = loss_dict["loss"]
            if not total_loss.requires_grad:
                total_loss = _build_pose_zero_grad_loss(raw_for_loss, torch)
            optimizer_step.backward_and_step(
                loss=total_loss,
                iteration_index=global_iteration,
                is_last_batch=(epoch + 1 == max_epochs and iteration == max_iterations),
            )

            batch_sample_count = len(targets)
            for k, v in loss_dict.items():
                metric_value = float(v.item())
                if k == "loss":
                    metric_value /= batch_sample_count
                epoch_losses[k] = (
                    epoch_losses.get(k, 0.0) + metric_value * batch_sample_count
                )
            epoch_iters += 1
            epoch_samples += batch_sample_count
            if request.batch_callback is not None:
                batch_metrics: dict[str, float] = {}
                for name, value in loss_dict.items():
                    metric_value = float(value.item())
                    if name == "loss":
                        metric_value /= max(1, batch_sample_count)
                    batch_metrics[name] = round(metric_value, 6)
                request.batch_callback(
                    YoloV8PoseTrainingBatchProgress(
                        epoch=epoch,
                        max_epochs=max_epochs,
                        iteration=iteration,
                        max_iterations=max_iterations,
                        global_iteration=global_iteration,
                        total_iterations=max_epochs * max_iterations,
                        input_size=input_size,
                        learning_rate=resolve_yolo_optimizer_base_learning_rate(
                            optimizer=optimizer,
                            initial_learning_rate=training_schedule.initial_lr,
                        ),
                        train_metrics=batch_metrics,
                    )
                )

        if epoch_samples > 0:
            avg_metrics = {
                k: round(v / epoch_samples, 6) for k, v in epoch_losses.items()
            }
        else:
            avg_metrics = {"loss": 0.0}

        metrics_history.append(
            build_yolo_epoch_history_item(epoch_index=epoch, metrics=avg_metrics)
        )

        val_metrics: dict[str, float] = {}
        should_evaluate = should_run_yolo_validation(
            epoch_index=epoch,
            max_epochs=max_epochs,
            evaluation_interval=request.evaluation_interval,
            has_validation_samples=bool(val_anns),
        )
        if should_evaluate:
            val_metrics = evaluate_yolov8_pose_samples(
                model=ema.model,
                samples=val_anns,
                labels=labels,
                input_size=input_size,
                device=device,
                precision=precision,
                score_threshold=float(
                    extra.get("evaluation_confidence_threshold", 0.001)
                ),
                nms_threshold=float(extra.get("evaluation_nms_threshold", 0.7)),
                kpt_shape=kpt_shape,
                imports=_build_yolo_training_imports(cv2, np, torch),
                batch_size=bs,
                control_callback=observe_control,
            )
            validation_history.append(
                build_yolo_epoch_history_item(epoch_index=epoch, metrics=val_metrics)
            )
            current_metric = float(val_metrics.get("oks_ap50_95", 0.0))
            best_metric_improved = is_better_training_metric(
                current_value=current_metric,
                best_value=best_metric_value,
                direction="maximize",
                maximum=1.0,
            )
            if best_metric_improved:
                best_metric_value = current_metric
                best_metric_name = "val_oks_ap50_95"
        else:
            best_metric_improved = False

        optimizer_step.step_scheduler_if_optimizer_updated(scheduler)
        ep_progress = YoloV8PoseTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            input_size=input_size,
            learning_rate=resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            train_metrics=avg_metrics,
            validation_metrics=val_metrics or None,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
        )
        cmd = request.epoch_callback(ep_progress) if request.epoch_callback else None
        checkpoint_decision = resolve_training_checkpoint_persistence_decision(
            completed_epoch=epoch + 1,
            max_epochs=max_epochs,
            interval_epochs=read_training_checkpoint_interval(extra),
            best_improved=best_metric_improved,
            manual_save_requested=bool(cmd and cmd.save_checkpoint),
            pause_requested=bool(cmd and cmd.pause_training),
            terminate_requested=bool(cmd and cmd.terminate_training),
        )
        ckpt_bytes = build_completed_epoch_checkpoint(epoch + 1)
        if best_metric_improved:
            best_checkpoint_bytes = ckpt_bytes

        last_completed_savepoint = YoloV8PoseTrainingSavePoint(
            latest_checkpoint_bytes=ckpt_bytes,
            train_metrics=avg_metrics,
            validation_metrics=val_metrics,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            epoch=epoch + 1,
            learning_rate=resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            is_best=best_metric_improved,
        )
        if checkpoint_decision.should_persist and request.savepoint_callback:
            request.savepoint_callback(last_completed_savepoint)

        if cmd and cmd.pause_training:
            raise YoloV8PoseTrainingPausedError()
        if cmd and cmd.terminate_training:
            raise YoloV8PoseTrainingTerminatedError()

    training_loader_lifecycle.close()
    optimizer_step.require_successful_optimizer_step(
        task_name=f"{request.model_type.upper()} pose",
    )
    if not best_checkpoint_bytes:
        best_checkpoint_bytes = ckpt_bytes
    test_metrics_payload = build_detection_test_metrics_report(
        available=False,
        sample_count=0,
        category_names=labels,
        reason="dataset export does not contain an independent test split",
        task_type="pose",
    )
    if test_anns:
        checkpoint_payload = torch.load(
            io.BytesIO(best_checkpoint_bytes),
            map_location="cpu",
            weights_only=False,
        )
        best_state_dict = checkpoint_payload.get("ema_state_dict")
        if not isinstance(best_state_dict, dict):
            best_state_dict = checkpoint_payload.get("model_state_dict")
        if not isinstance(best_state_dict, dict):
            raise InvalidRequestError("YOLOv8 pose best checkpoint 缺少模型权重")
        ema.model.load_state_dict(best_state_dict, strict=False)
        ema.model.to(device)
        test_metrics = evaluate_yolov8_pose_samples(
            model=ema.model,
            samples=test_anns,
            labels=labels,
            input_size=input_size,
            device=device,
            precision=precision,
            score_threshold=float(extra.get("evaluation_confidence_threshold", 0.001)),
            nms_threshold=float(extra.get("evaluation_nms_threshold", 0.7)),
            kpt_shape=kpt_shape,
            imports=_build_yolo_training_imports(cv2, np, torch),
            batch_size=bs,
            control_callback=observe_control,
        )
        test_metrics_payload = build_detection_test_metrics_report(
            available=True,
            sample_count=len(test_anns),
            metrics=test_metrics,
            category_names=labels,
            task_type="pose",
        )
    return YoloV8PoseTrainingExecutionResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=ckpt_bytes,
        metrics_payload={
            "final_metrics": metrics_history[-1] if metrics_history else {},
            "epoch_history": metrics_history,
            "optimizer": training_schedule.optimizer_name,
            "initial_learning_rate": training_schedule.initial_lr,
            "final_learning_rate": resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            "kpt_shape": list(kpt_shape),
        },
        validation_metrics_payload={
            "final_metrics": validation_history[-1] if validation_history else {},
            "epoch_history": validation_history,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
        best_checkpoint_bytes=best_checkpoint_bytes,
        test_metrics_payload=test_metrics_payload,
        test_split_name="test" if test_anns else None,
        test_sample_count=len(test_anns),
    )


def _build_yolo_training_imports(cv2: Any, np: Any, torch: Any) -> Any:
    """构建 YOLO task core data/evaluation 使用的依赖对象。"""

    from types import SimpleNamespace

    return SimpleNamespace(cv2=cv2, np=np, torch=torch)


def _build_pose_zero_grad_loss(raw_outputs: Any, torch: Any) -> Any:
    """用模型输出构建可反传的零损失。"""

    if torch.is_tensor(raw_outputs):
        return raw_outputs.sum() * 0.0
    if isinstance(raw_outputs, dict):
        tensors = [
            _build_pose_zero_grad_loss(value, torch)
            for value in raw_outputs.values()
            if _contains_pose_tensor(value, torch)
        ]
    elif isinstance(raw_outputs, list | tuple):
        tensors = [
            _build_pose_zero_grad_loss(value, torch)
            for value in raw_outputs
            if _contains_pose_tensor(value, torch)
        ]
    else:
        tensors = []
    if tensors:
        return sum(tensors)
    return torch.zeros((), requires_grad=True)


def _contains_pose_tensor(value: Any, torch: Any) -> bool:
    """判断输出结构里是否包含 torch Tensor。"""

    if torch.is_tensor(value):
        return True
    if isinstance(value, dict):
        return any(_contains_pose_tensor(item, torch) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_pose_tensor(item, torch) for item in value)
    return False


def _load_pose_manifest(
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
) -> tuple[
    tuple[str, ...],
    list[_PoseAnnotation],
    list[_PoseAnnotation],
    list[_PoseAnnotation],
]:
    """加载 COCO keypoints 格式的 Pose manifest。"""

    splits = manifest.get("splits", [])
    format_id = str(manifest.get("format_id") or COCO_KEYPOINTS_DATASET_FORMAT).strip()
    yolo_category_names = (
        normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLO pose",
        )
        if format_id == YOLO_POSE_DATASET_FORMAT
        else ()
    )
    all_categories: dict[int, str] = {}
    train_anns: list[_PoseAnnotation] = []
    val_anns: list[_PoseAnnotation] = []
    test_anns: list[_PoseAnnotation] = []

    for split in splits or []:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", "")).strip().lower()
        image_root = str(split.get("image_root", ""))
        if format_id == YOLO_POSE_DATASET_FORMAT:
            label_root = str(split.get("label_root", ""))
            image_root_path = dataset_storage.resolve_filesystem_path(image_root)
            label_root_path = dataset_storage.resolve_filesystem_path(label_root)
            if not image_root_path.is_dir():
                raise InvalidRequestError(
                    "pose 训练 split 缺少图片目录",
                    details={"split_name": split_name, "image_root": image_root},
                )
            if not label_root_path.is_dir():
                raise InvalidRequestError(
                    "pose 训练 split 缺少标签目录",
                    details={"split_name": split_name, "label_root": label_root},
                )
            payload = build_coco_payload_from_yolo_pose_split(
                split_name=split_name,
                image_root=image_root_path,
                label_root=label_root_path,
                category_names=yolo_category_names,
                pose_shape=_read_pose_keypoint_shape_from_manifest(manifest),
            )
        else:
            annotation_file = str(split.get("annotation_file", ""))
            annotation_path = dataset_storage.resolve_filesystem_path(annotation_file)
            if not annotation_path.is_file():
                continue

            payload = dataset_storage.read_json(annotation_file)
            if not isinstance(payload, dict):
                continue

        for cat in payload.get("categories") or []:
            if isinstance(cat, dict):
                all_categories[int(cat.get("id", -1))] = str(cat.get("name", ""))

        image_map: dict[int, str] = {}
        for img in payload.get("images") or []:
            if isinstance(img, dict):
                image_map[int(img.get("id", -1))] = str(img.get("file_name", ""))

        annotations_by_image: dict[int, list[dict[str, Any]]] = {}
        for ann in payload.get("annotations") or []:
            if not isinstance(ann, dict):
                continue
            img_id = int(ann.get("image_id", -1))
            annotations_by_image.setdefault(img_id, []).append(ann)

        records: list[_PoseAnnotation] = []
        for img_id, file_name in image_map.items():
            anns = annotations_by_image.get(img_id, [])
            boxes: list[list[float]] = []
            class_ids: list[int] = []
            keypoints: list[list[float]] = []
            for ann in anns:
                bb = ann.get("bbox")
                if not isinstance(bb, list) or len(bb) != 4:
                    continue
                boxes.append([float(v) for v in bb])
                class_ids.append(int(ann.get("category_id", -1)))
                kp = ann.get("keypoints")
                if isinstance(kp, list) and len(kp) > 0:
                    keypoints.append([float(v) for v in kp])
                else:
                    keypoints.append([])
            records.append(
                _PoseAnnotation(
                    image_path=str(
                        dataset_storage.resolve_filesystem_path(
                            f"{image_root}/{file_name}"
                        )
                    ),
                    boxes_xywh=boxes,
                    class_ids=class_ids,
                    keypoints=keypoints,
                )
            )

        if split_name == "train":
            train_anns = records
        elif split_name in ("val", "valid", "validation"):
            val_anns = records
        elif split_name == "test":
            test_anns = records

    sorted_cats = sorted(all_categories.items())
    cat_id_map = {cid: idx for idx, (cid, _) in enumerate(sorted_cats)}
    labels = tuple(name for _, name in sorted_cats)

    if not labels:
        raise InvalidRequestError("YOLOv8 pose 训练集没有合法类别")
    if not train_anns:
        raise InvalidRequestError("YOLOv8 pose 训练集没有合法样本")
    if not val_anns:
        raise InvalidRequestError(
            "YOLOv8 pose 训练需要独立 validation split，禁止使用 train 或 test 回退"
        )

    def remap(anns: list[_PoseAnnotation]) -> list[_PoseAnnotation]:
        remapped: list[_PoseAnnotation] = []
        for annotation in anns:
            unknown_ids = sorted(
                {
                    class_id
                    for class_id in annotation.class_ids
                    if class_id not in cat_id_map
                }
            )
            if unknown_ids:
                raise InvalidRequestError(
                    "YOLOv8 pose 标注引用了未声明类别",
                    details={
                        "category_ids": unknown_ids,
                        "image_path": annotation.image_path,
                    },
                )
            remapped.append(
                _PoseAnnotation(
                    annotation.image_path,
                    annotation.boxes_xywh,
                    [cat_id_map[class_id] for class_id in annotation.class_ids],
                    annotation.keypoints,
                )
            )
        return remapped

    return labels, remap(train_anns), remap(val_anns), remap(test_anns)


def _resolve_pose_keypoint_shape_from_manifest(
    manifest: dict[str, object],
) -> tuple[int, int]:
    """从 pose manifest metadata 中读取 kpt_shape，缺省时回退到 COCO pose。"""

    return _read_pose_keypoint_shape_from_manifest(manifest) or _POSE_DEF_KPT_SHAPE


def _read_pose_keypoint_shape_from_manifest(
    manifest: dict[str, object],
) -> tuple[int, int] | None:
    """从 pose manifest metadata 中读取可选 kpt_shape。"""

    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw_shape = metadata.get("kpt_shape")
    if not isinstance(raw_shape, list) and not isinstance(raw_shape, tuple):
        return None
    if len(raw_shape) < 2:
        return None
    try:
        keypoint_count = int(raw_shape[0])
        point_dimensions = int(raw_shape[1])
    except (TypeError, ValueError):
        return None
    if keypoint_count <= 0 or point_dimensions not in {2, 3}:
        return None
    return (keypoint_count, point_dimensions)


def _resolve_pose_keypoint_shape_from_annotations(
    *,
    manifest: dict[str, object],
    train_annotations: list[_PoseAnnotation],
    val_annotations: list[_PoseAnnotation],
) -> tuple[int, int]:
    """从 manifest 或已解析标注中推断 pose keypoint shape。"""

    manifest_shape = _read_pose_keypoint_shape_from_manifest(manifest)
    if manifest_shape is not None:
        return manifest_shape
    for annotation in (*train_annotations, *val_annotations):
        for keypoints in annotation.keypoints or []:
            if len(keypoints) > 0 and len(keypoints) % 3 == 0:
                return (len(keypoints) // 3, 3)
    return _POSE_DEF_KPT_SHAPE
