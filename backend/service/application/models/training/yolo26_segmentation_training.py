"""YOLO26 segmentation 专属训练执行入口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.application.models.yolo26_core import build_yolo26_model
from backend.service.application.models.yolo26_core.assigners import (
    assign_yolo26_segmentation_targets,
)
from backend.service.application.models.yolo26_core.data import (
    build_yolo26_segmentation_training_batch,
    build_yolo26_task_augmentation_options,
    resolve_yolo26_task_augmentation_for_epoch,
    resolve_yolo26_task_batch_input_size,
)
from backend.service.application.models.yolo26_core.evaluation import (
    evaluate_yolo26_segmentation_samples,
)
from backend.service.application.models.yolo26_core.losses import (
    combine_yolo26_end2end_loss_payloads,
    compute_yolo26_segmentation_detection_loss,
    compute_yolo26_segmentation_mask_loss,
    resolve_yolo26_end2end_loss_weights,
)
from backend.service.application.models.yolo26_core.training.segmentation_anchors import (
    build_yolo26_segmentation_anchors_from_features,
)
from backend.service.application.models.yolo26_core.training.segmentation_checkpoint import (
    build_yolo26_segmentation_checkpoint_bytes,
    load_yolo26_segmentation_resume_state,
    restore_yolo26_segmentation_training_state,
    validate_yolo26_segmentation_resume_parameters,
)
from backend.service.application.models.yolo26_core.training.segmentation_imports import (
    build_yolo26_segmentation_autocast_context,
    require_yolo26_segmentation_training_imports,
    resolve_yolo26_segmentation_training_device,
)
from backend.service.application.models.yolo26_core.training.segmentation_manifest import (
    load_yolo26_segmentation_training_manifest,
)
from backend.service.application.models.yolo26_core.weights import (
    load_yolo26_checkpoint_file,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO26_SEGMENTATION_IMPLEMENTATION_MODE = "yolo26-segmentation-core"
YOLO26_SEGMENTATION_DEFAULT_INPUT_SIZE = (640, 640)
YOLO26_SEGMENTATION_DEFAULT_BATCH_SIZE = 1
YOLO26_SEGMENTATION_DEFAULT_MAX_EPOCHS = 1
YOLO26_SEGMENTATION_DEFAULT_EVAL_INTERVAL = 5
YOLO26_SEGMENTATION_DEFAULT_EVAL_CONF = 0.001
YOLO26_SEGMENTATION_DEFAULT_EVAL_NMS = 0.7
YOLO26_SEGMENTATION_DEFAULT_ASSIGN_TOPK = 10
YOLO26_SEGMENTATION_DEFAULT_CLASS_LOSS = 0.5
YOLO26_SEGMENTATION_DEFAULT_BOX_LOSS = 7.5
YOLO26_SEGMENTATION_DEFAULT_DFL_LOSS = 1.5
YOLO26_SEGMENTATION_DEFAULT_MASK_LOSS = 1.0
YOLO26_SEGMENTATION_DEFAULT_ASSIGN_ALPHA = 0.5
YOLO26_SEGMENTATION_DEFAULT_ASSIGN_BETA = 6.0
YOLO26_SEGMENTATION_DEFAULT_LR = 1e-3
YOLO26_SEGMENTATION_DEFAULT_WEIGHT_DECAY = 1e-4
YOLO26_SEGMENTATION_DEFAULT_MIN_LR = 0.01
YOLO26_SEGMENTATION_DEFAULT_GRAD_CLIP = 10.0


@dataclass(frozen=True)
class Yolo26SegmentationTrainingEpochProgress:
    """描述 YOLO26 segmentation 单轮训练进度。"""

    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class Yolo26SegmentationTrainingSavePoint:
    """描述 YOLO26 segmentation 训练保存点。"""

    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class Yolo26SegmentationTrainingControlCommand:
    """描述 YOLO26 segmentation 训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class Yolo26SegmentationTrainingExecutionRequest:
    """描述一次 YOLO26 segmentation 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = YOLO26_SEGMENTATION_DEFAULT_BATCH_SIZE
    max_epochs: int = YOLO26_SEGMENTATION_DEFAULT_MAX_EPOCHS
    evaluation_interval: int = YOLO26_SEGMENTATION_DEFAULT_EVAL_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: (
        Callable[
            [Yolo26SegmentationTrainingEpochProgress],
            Yolo26SegmentationTrainingControlCommand | None,
        ]
        | None
    ) = None
    savepoint_callback: Callable[[Yolo26SegmentationTrainingSavePoint], None] | None = (
        None
    )


@dataclass(frozen=True)
class Yolo26SegmentationTrainingExecutionResult:
    """描述一次 YOLO26 segmentation 训练执行结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    warm_start_summary: dict[str, object]


class Yolo26SegmentationTrainingPausedError(Exception):
    """YOLO26 segmentation 训练被显式暂停。"""


class Yolo26SegmentationTrainingTerminatedError(Exception):
    """YOLO26 segmentation 训练被显式终止。"""


def run_yolo26_segmentation_training(
    request: Yolo26SegmentationTrainingExecutionRequest,
) -> Yolo26SegmentationTrainingExecutionResult:
    """执行一次 YOLO26 segmentation 训练。"""

    if request.model_type != "yolo26":
        raise InvalidRequestError(
            "YOLO26 segmentation 训练入口只接受 model_type=yolo26",
            details={"model_type": request.model_type},
        )

    imports = require_yolo26_segmentation_training_imports()
    device = resolve_yolo26_segmentation_training_device(
        torch_module=imports.torch,
        extra_options=request.extra_options,
    )
    precision = request.precision
    input_size = request.input_size or YOLO26_SEGMENTATION_DEFAULT_INPUT_SIZE
    manifest = load_yolo26_segmentation_training_manifest(
        dataset_storage=request.dataset_storage,
        manifest_payload=request.manifest_payload,
    )
    labels = manifest.labels
    train_annotations = manifest.train_annotations
    val_annotations = manifest.val_annotations

    model = build_yolo26_model(
        task_type=SEGMENTATION_TASK_TYPE,
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
        )
        warm_start_summary = build_yolo_warm_start_summary(
            load_result=load_result,
            source_summary=request.warm_start_source_summary,
        )
    resume = None
    if (
        request.resume_checkpoint_path is not None
        and request.resume_checkpoint_path.is_file()
    ):
        resume = load_yolo26_segmentation_resume_state(
            checkpoint_path=request.resume_checkpoint_path,
            torch_module=imports.torch,
        )

    extra = dict(request.extra_options or {})
    learning_rate = float(
        extra.get("learning_rate", YOLO26_SEGMENTATION_DEFAULT_LR)
    )
    weight_decay = float(
        extra.get("weight_decay", YOLO26_SEGMENTATION_DEFAULT_WEIGHT_DECAY)
    )
    min_lr_ratio = float(extra.get("min_lr_ratio", YOLO26_SEGMENTATION_DEFAULT_MIN_LR))
    batch_size = max(1, int(extra.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra.get("max_epochs", request.max_epochs)))
    evaluation_interval = max(
        1,
        int(extra.get("evaluation_interval", request.evaluation_interval)),
    )
    class_loss_weight = float(
        extra.get("class_loss_weight", YOLO26_SEGMENTATION_DEFAULT_CLASS_LOSS)
    )
    box_loss_weight = float(
        extra.get("box_loss_weight", YOLO26_SEGMENTATION_DEFAULT_BOX_LOSS)
    )
    dfl_loss_weight = float(
        extra.get("dfl_loss_weight", YOLO26_SEGMENTATION_DEFAULT_DFL_LOSS)
    )
    mask_loss_weight = float(
        extra.get("mask_loss_weight", YOLO26_SEGMENTATION_DEFAULT_MASK_LOSS)
    )
    assign_topk = max(
        1, int(extra.get("assign_topk", YOLO26_SEGMENTATION_DEFAULT_ASSIGN_TOPK))
    )
    assign_alpha = float(
        extra.get("assign_alpha", YOLO26_SEGMENTATION_DEFAULT_ASSIGN_ALPHA)
    )
    assign_beta = float(
        extra.get("assign_beta", YOLO26_SEGMENTATION_DEFAULT_ASSIGN_BETA)
    )
    grad_clip = max(
        0.0, float(extra.get("grad_clip_norm", YOLO26_SEGMENTATION_DEFAULT_GRAD_CLIP))
    )
    eval_conf = float(
        extra.get(
            "evaluation_confidence_threshold", YOLO26_SEGMENTATION_DEFAULT_EVAL_CONF
        )
    )
    eval_nms = float(
        extra.get("evaluation_nms_threshold", YOLO26_SEGMENTATION_DEFAULT_EVAL_NMS)
    )
    augmentation_options = build_yolo26_task_augmentation_options(extra)

    if resume is not None:
        validate_yolo26_segmentation_resume_parameters(
            state=resume,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
            class_loss_weight=class_loss_weight,
            box_loss_weight=box_loss_weight,
            dfl_loss_weight=dfl_loss_weight,
            mask_loss_weight=mask_loss_weight,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            grad_clip_norm=grad_clip,
            evaluation_confidence_threshold=eval_conf,
            evaluation_nms_threshold=eval_nms,
        )

    model.to(device)
    trainable = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]
    optimizer = imports.torch.optim.AdamW(
        trainable,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    scaler = (
        imports.torch.amp.GradScaler(device, enabled=precision == "fp16")
        if hasattr(imports.torch, "amp") and hasattr(imports.torch.amp, "GradScaler")
        else None
    )
    total_iterations = max_epochs * max(
        1,
        (len(train_annotations) + batch_size - 1) // batch_size,
    )
    scheduler = imports.torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=total_iterations,
        eta_min=learning_rate * min_lr_ratio,
    )

    start_epoch = 0
    global_iteration = 0
    metrics_history: list[dict[str, float]] = []
    validation_history: list[dict[str, float]] = []
    best_metric_value = 0.0
    best_metric_name = "val_map50_95"
    latest_checkpoint_bytes = b""
    if resume is not None:
        restore_yolo26_segmentation_training_state(
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            state=resume,
            device_name=device,
        )
        metrics_history = list(resume.metrics_history)
        validation_history = list(resume.validation_history)
        best_metric_value = resume.best_metric_value
        best_metric_name = resume.best_metric_name
        start_epoch = resume.epoch
        global_iteration = resume.global_iteration

    stride_values = model.stride if hasattr(model, "stride") else (8, 16, 32)
    num_classes = len(labels)
    for epoch in range(start_epoch, max_epochs):
        model.train()
        train_metrics, global_iteration = _run_yolo26_segmentation_epoch(
            imports=imports,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            trainable_parameters=trainable,
            train_annotations=train_annotations,
            batch_size=batch_size,
            base_input_size=input_size,
            precision=precision,
            device=device,
            epoch=epoch,
            max_epochs=max_epochs,
            global_iteration=global_iteration,
            augmentation_options=augmentation_options,
            stride_values=stride_values,
            num_classes=num_classes,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            class_loss_weight=class_loss_weight,
            box_loss_weight=box_loss_weight,
            dfl_loss_weight=dfl_loss_weight,
            mask_loss_weight=mask_loss_weight,
            grad_clip=grad_clip,
        )
        metrics_history.append({"epoch": epoch, **train_metrics})
        progress = Yolo26SegmentationTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=train_metrics,
        )
        command = (
            request.epoch_callback(progress)
            if request.epoch_callback is not None
            else None
        )
        if command is not None and command.terminate_training:
            raise Yolo26SegmentationTrainingTerminatedError()

        val_metrics = _run_yolo26_segmentation_validation(
            imports=imports,
            model=model,
            val_annotations=val_annotations,
            labels=labels,
            input_size=input_size,
            device=device,
            precision=precision,
            evaluation_confidence_threshold=eval_conf,
            evaluation_nms_threshold=eval_nms,
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
        )
        if val_metrics:
            validation_history.append({"epoch": epoch, **val_metrics})
        current_metric = float(val_metrics.get("map50_95", 0.0))
        if current_metric > best_metric_value:
            best_metric_value = current_metric
            best_metric_name = "val_map50_95"

        latest_checkpoint_bytes = build_yolo26_segmentation_checkpoint_bytes(
            epoch=epoch,
            global_iteration=global_iteration,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            metrics_history=metrics_history,
            validation_history=validation_history,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
            class_loss_weight=class_loss_weight,
            box_loss_weight=box_loss_weight,
            dfl_loss_weight=dfl_loss_weight,
            mask_loss_weight=mask_loss_weight,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            grad_clip_norm=grad_clip,
            evaluation_confidence_threshold=eval_conf,
            evaluation_nms_threshold=eval_nms,
            torch_module=imports.torch,
        )
        if command is not None and request.savepoint_callback is not None:
            request.savepoint_callback(
                Yolo26SegmentationTrainingSavePoint(
                    latest_checkpoint_bytes=latest_checkpoint_bytes,
                    train_metrics=train_metrics,
                    validation_metrics=val_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )
        if command is not None and command.pause_training:
            raise Yolo26SegmentationTrainingPausedError()

    final_validation = validation_history[-1] if validation_history else {}
    return Yolo26SegmentationTrainingExecutionResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload={
            "final_metrics": metrics_history[-1] if metrics_history else {},
            "epoch_history": metrics_history,
            "scheduler": "CosineAnnealingLR",
        },
        validation_metrics_payload={
            "final_metrics": final_validation,
            "epoch_history": validation_history,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
    )


def _run_yolo26_segmentation_epoch(
    *,
    imports: Any,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
    trainable_parameters: list[Any],
    train_annotations: list[Any],
    batch_size: int,
    base_input_size: tuple[int, int],
    precision: str,
    device: str,
    epoch: int,
    max_epochs: int,
    global_iteration: int,
    augmentation_options: Any,
    stride_values: tuple[int, ...],
    num_classes: int,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    mask_loss_weight: float,
    grad_clip: float,
) -> tuple[dict[str, float], int]:
    """执行 YOLO26 segmentation 单轮训练。"""

    total_loss_sum = 0.0
    class_loss_sum = 0.0
    box_loss_sum = 0.0
    dfl_loss_sum = 0.0
    mask_loss_sum = 0.0
    iteration_count = 0
    effective_augmentation_options = resolve_yolo26_task_augmentation_for_epoch(
        augmentation_options=augmentation_options,
        epoch_index=epoch,
        max_epochs=max_epochs,
    )
    for batch_start in range(0, len(train_annotations), batch_size):
        batch_annotations = train_annotations[batch_start : batch_start + batch_size]
        batch_input_size = resolve_yolo26_task_batch_input_size(
            base_input_size=base_input_size,
            augmentation_options=effective_augmentation_options,
        )
        batch = build_yolo26_segmentation_training_batch(
            samples=batch_annotations,
            input_size=batch_input_size,
            device=device,
            precision=precision,
            imports=imports,
            augmentation_options=effective_augmentation_options,
            available_samples=train_annotations,
        )
        if batch is None:
            continue
        with build_yolo26_segmentation_autocast_context(
            torch_module=imports.torch,
            precision=precision,
            device_name=device,
        ):
            outputs = model(batch.images)
            raw_outputs = _normalize_yolo26_segmentation_training_outputs(outputs)
            if raw_outputs is None:
                continue
            loss_payload = _compute_yolo26_segmentation_training_loss(
                imports=imports,
                model=model,
                raw_outputs=raw_outputs,
                targets_list=batch.targets,
                stride_values=stride_values,
                device=device,
                num_classes=num_classes,
                assign_topk=assign_topk,
                assign_alpha=assign_alpha,
                assign_beta=assign_beta,
                dfl_loss_weight=dfl_loss_weight,
                epoch=epoch + 1,
                max_epochs=max_epochs,
            )
        total_loss = (
            class_loss_weight * loss_payload["class_loss"]
            + box_loss_weight * loss_payload["box_loss"]
            + dfl_loss_weight * loss_payload["dfl_loss"]
            + mask_loss_weight * loss_payload["mask_loss"]
        )
        total_loss = total_loss * max(1, len(batch.targets))
        if not total_loss.requires_grad:
            total_loss = loss_payload["fallback_tensor"].sum() * 0.0
        optimizer.zero_grad()
        if scaler is not None:
            scaler.scale(total_loss).backward()
            if grad_clip > 0:
                scaler.unscale_(optimizer)
                imports.torch.nn.utils.clip_grad_norm_(trainable_parameters, grad_clip)
            scaler.step(optimizer)
            scaler.update()
        else:
            total_loss.backward()
            if grad_clip > 0:
                imports.torch.nn.utils.clip_grad_norm_(trainable_parameters, grad_clip)
            optimizer.step()
        scheduler.step()
        total_loss_sum += float(total_loss.item())
        class_loss_sum += float(loss_payload["class_loss"].item())
        box_loss_sum += float(loss_payload["box_loss"].item())
        dfl_loss_sum += float(loss_payload["dfl_loss"].item())
        mask_loss_sum += float(loss_payload["mask_loss"].item())
        iteration_count += 1
        global_iteration += 1

    divisor = max(1, iteration_count)
    return (
        {
            "loss": round(total_loss_sum / divisor, 6),
            "class_loss": round(class_loss_sum / divisor, 6),
            "box_loss": round(box_loss_sum / divisor, 6),
            "dfl_loss": round(dfl_loss_sum / divisor, 6),
            "mask_loss": round(mask_loss_sum / divisor, 6),
        },
        global_iteration,
    )


def _normalize_yolo26_segmentation_training_outputs(
    outputs: Any,
) -> dict[str, Any] | None:
    """把 YOLO26 segmentation 训练输出规整成 loss 输入字典。"""

    if isinstance(outputs, dict) and "one2many" in outputs and "one2one" in outputs:
        one2many = outputs.get("one2many")
        one2one = outputs.get("one2one")
        if (
            isinstance(one2many, dict)
            and isinstance(one2one, dict)
            and "boxes" in one2many
            and "boxes" in one2one
        ):
            return outputs
        return None
    if isinstance(outputs, dict) and "one2many" in outputs:
        raw_outputs = outputs["one2many"]
    elif isinstance(outputs, dict):
        raw_outputs = outputs
    else:
        return None
    if not isinstance(raw_outputs, dict) or "boxes" not in raw_outputs:
        return None
    return raw_outputs


def _compute_yolo26_segmentation_training_loss(
    *,
    imports: Any,
    model: Any,
    raw_outputs: dict[str, Any],
    targets_list: list[dict[str, Any]],
    stride_values: tuple[int, ...],
    device: str,
    num_classes: int,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    dfl_loss_weight: float,
    assign_topk2: int | None = None,
    epoch: int = 1,
    max_epochs: int = 1,
) -> dict[str, Any]:
    """计算 YOLO26 segmentation 单个 batch 的训练损失。"""

    if "one2many" in raw_outputs and "one2one" in raw_outputs:
        one2many_payload = _compute_yolo26_segmentation_training_loss(
            imports=imports,
            model=model,
            raw_outputs=raw_outputs["one2many"],
            targets_list=targets_list,
            stride_values=stride_values,
            device=device,
            num_classes=num_classes,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            dfl_loss_weight=dfl_loss_weight,
            assign_topk2=None,
        )
        one2one_payload = _compute_yolo26_segmentation_training_loss(
            imports=imports,
            model=model,
            raw_outputs=raw_outputs["one2one"],
            targets_list=targets_list,
            stride_values=stride_values,
            device=device,
            num_classes=num_classes,
            assign_topk=7,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            dfl_loss_weight=dfl_loss_weight,
            assign_topk2=1,
        )
        one2many_weight, one2one_weight = resolve_yolo26_end2end_loss_weights(
            epoch=epoch,
            max_epochs=max_epochs,
        )
        return combine_yolo26_end2end_loss_payloads(
            one2many_payload=one2many_payload,
            one2one_payload=one2one_payload,
            one2many_weight=one2many_weight,
            one2one_weight=one2one_weight,
        )

    raw_boxes = raw_outputs["boxes"]
    raw_scores = raw_outputs["scores"]
    feature_maps = raw_outputs.get("feats", [])
    raw_mask_coefficients = raw_outputs.get("mask_coefficients")
    proto = raw_outputs.get("proto")
    anchor_points, stride_tensor = build_yolo26_segmentation_anchors_from_features(
        feature_maps=feature_maps,
        strides=stride_values,
        device_name=device,
        torch_module=imports.torch,
    )
    segment_head = model.model[-1]
    if int(getattr(segment_head, "reg_max", 1)) > 1:
        decoded_distances = segment_head.dfl(raw_boxes)
    else:
        decoded_distances = imports.torch.nn.functional.softplus(raw_boxes)
    prediction_parts = [
        decoded_distances.permute(0, 2, 1).contiguous(),
        raw_scores.permute(0, 2, 1).contiguous(),
    ]
    if raw_mask_coefficients is not None:
        prediction_parts.append(raw_mask_coefficients.permute(0, 2, 1).contiguous())
    predictions = imports.torch.cat(prediction_parts, dim=-1)
    distance_logits = raw_boxes.permute(0, 2, 1).contiguous()
    class_loss = imports.torch.zeros(1, device=device)
    box_loss = imports.torch.zeros(1, device=device)
    dfl_loss = imports.torch.zeros(1, device=device)
    mask_loss = imports.torch.zeros(1, device=device)
    for batch_index, targets in enumerate(targets_list):
        assignment = assign_yolo26_segmentation_targets(
            torch_module=imports.torch,
            targets=targets,
            prediction=predictions[batch_index],
            anchor_points=anchor_points,
            stride_tensor=stride_tensor,
            topk=assign_topk,
            alpha=assign_alpha,
            beta=assign_beta,
            num_classes=num_classes,
            topk2=assign_topk2,
        )
        if assignment is None:
            continue
        current_class_loss, current_box_loss, current_dfl_loss = (
            compute_yolo26_segmentation_detection_loss(
                torch_module=imports.torch,
                prediction=predictions[batch_index],
                assignment=assignment,
                anchor_points=anchor_points,
                stride_tensor=stride_tensor,
                dfl_weight=dfl_loss_weight,
                num_classes=num_classes,
                distance_logits=distance_logits[batch_index],
                reg_max=int(getattr(segment_head, "reg_max", 1)),
            )
        )
        class_loss += current_class_loss
        box_loss += current_box_loss
        dfl_loss += current_dfl_loss
        if proto is not None and raw_mask_coefficients is not None:
            mask_loss += compute_yolo26_segmentation_mask_loss(
                torch_module=imports.torch,
                prediction=predictions[batch_index],
                proto=proto[batch_index],
                foreground_mask=assignment.fg_mask.to(device),
                target_masks=assignment.mask_targets,
                target_mask_valid=assignment.mask_valid,
                matched_gt_indices=assignment.matched_gt_indices,
                num_classes=num_classes,
                target_boxes=assignment.box_targets,
            )
    return {
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
        "mask_loss": mask_loss,
        "fallback_tensor": raw_scores,
    }


def _run_yolo26_segmentation_validation(
    *,
    imports: Any,
    model: Any,
    val_annotations: list[Any],
    labels: tuple[str, ...],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
) -> dict[str, float]:
    """按 YOLO26 segmentation 规则执行训练期 validation。"""

    should_evaluate = (
        len(val_annotations) > 0 and epoch > 0 and epoch % evaluation_interval == 0
    ) or epoch == max_epochs - 1
    if not should_evaluate:
        return {}
    return evaluate_yolo26_segmentation_samples(
        model=model,
        samples=val_annotations,
        labels=labels,
        input_size=input_size,
        device=device,
        precision=precision,
        evaluation_confidence_threshold=evaluation_confidence_threshold,
        evaluation_nms_threshold=evaluation_nms_threshold,
        imports=imports,
    )


__all__ = [
    "YOLO26_SEGMENTATION_IMPLEMENTATION_MODE",
    "Yolo26SegmentationTrainingControlCommand",
    "Yolo26SegmentationTrainingEpochProgress",
    "Yolo26SegmentationTrainingExecutionRequest",
    "Yolo26SegmentationTrainingExecutionResult",
    "Yolo26SegmentationTrainingPausedError",
    "Yolo26SegmentationTrainingSavePoint",
    "Yolo26SegmentationTrainingTerminatedError",
    "run_yolo26_segmentation_training",
]
