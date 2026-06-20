"""YOLO26 OBB 主训练循环。"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo26_core.data import (
    build_yolo26_obb_training_batch,
    resolve_yolo26_task_augmentation_for_epoch,
    resolve_yolo26_task_batch_input_size,
)
from backend.service.application.models.yolo26_core.evaluation import (
    evaluate_yolo26_obb_samples,
)
from backend.service.application.models.yolo26_core.losses import (
    compute_yolo26_obb_loss,
)
from backend.service.application.models.yolo26_core.training.obb_checkpoint import (
    build_yolo26_obb_checkpoint_bytes,
)


@dataclass(frozen=True)
class Yolo26ObbTrainingEpochProgress:
    """描述 YOLO26 OBB 单轮训练进度。"""

    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class Yolo26ObbTrainingControlCommand:
    """描述 YOLO26 OBB 训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class Yolo26ObbTrainingSavePoint:
    """描述 YOLO26 OBB 训练保存点。"""

    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class Yolo26ObbTrainingLoopResult:
    """描述 YOLO26 OBB 完整训练循环结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_history: list[dict[str, float]]
    validation_history: list[dict[str, float]]


class Yolo26ObbTrainingPausedError(Exception):
    """表示 YOLO26 OBB 训练在 epoch 边界暂停。"""


class Yolo26ObbTrainingTerminatedError(Exception):
    """表示 YOLO26 OBB 训练在 epoch 边界终止。"""


def run_yolo26_obb_training_loop(
    *,
    imports: Any,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
    trainable_parameters: list[Any],
    autocast_context: Callable[[], Any],
    labels: tuple[str, ...],
    train_annotations: list[Any],
    val_annotations: list[Any],
    batch_size: int,
    max_epochs: int,
    evaluation_interval: int,
    input_size: tuple[int, int],
    precision: str,
    device_name: str,
    learning_rate: float,
    weight_decay: float,
    min_lr_ratio: float,
    assign_topk2: int | None,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
    augmentation_options: Any,
    start_epoch: int,
    global_iteration: int,
    metrics_history: list[dict[str, float]],
    validation_history: list[dict[str, float]],
    best_metric_value: float,
    best_metric_name: str,
    epoch_callback: Callable[
        [Yolo26ObbTrainingEpochProgress],
        Yolo26ObbTrainingControlCommand | None,
    ]
    | None = None,
    savepoint_callback: Callable[[Yolo26ObbTrainingSavePoint], None] | None = None,
) -> Yolo26ObbTrainingLoopResult:
    """执行 YOLO26 OBB 从 start epoch 到 max epoch 的完整训练循环。"""

    checkpoint_bytes = b""
    for epoch in range(start_epoch, max_epochs):
        model.train()
        epoch_metrics, global_iteration = _run_yolo26_obb_epoch(
            imports=imports,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            trainable_parameters=trainable_parameters,
            train_annotations=train_annotations,
            batch_size=batch_size,
            base_input_size=input_size,
            precision=precision,
            device_name=device_name,
            epoch=epoch,
            max_epochs=max_epochs,
            global_iteration=global_iteration,
            augmentation_options=augmentation_options,
            assign_topk2=assign_topk2,
            autocast_context=autocast_context,
        )
        metrics_history.append({"epoch": epoch, **epoch_metrics})
        epoch_progress = Yolo26ObbTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=epoch_metrics,
        )
        command = epoch_callback(epoch_progress) if epoch_callback is not None else None
        if command is not None and command.terminate_training:
            raise Yolo26ObbTrainingTerminatedError()

        validation_metrics = _run_yolo26_obb_validation(
            imports=imports,
            model=model,
            val_annotations=val_annotations,
            labels=labels,
            input_size=input_size,
            device_name=device_name,
            precision=precision,
            evaluation_confidence_threshold=evaluation_confidence_threshold,
            evaluation_nms_threshold=evaluation_nms_threshold,
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
        )
        if validation_metrics:
            validation_history.append({"epoch": epoch, **validation_metrics})
        current_metric = float(validation_metrics.get("map50_95", 0.0))
        if current_metric > best_metric_value:
            best_metric_value = current_metric
            best_metric_name = "val_map50_95"

        checkpoint_bytes = build_yolo26_obb_checkpoint_bytes(
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
            evaluation_confidence_threshold=evaluation_confidence_threshold,
            evaluation_nms_threshold=evaluation_nms_threshold,
            torch_module=imports.torch,
        )
        if command is not None and savepoint_callback is not None:
            savepoint_callback(
                Yolo26ObbTrainingSavePoint(
                    latest_checkpoint_bytes=checkpoint_bytes,
                    train_metrics=epoch_metrics,
                    validation_metrics=validation_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )
        if command is not None and command.pause_training:
            raise Yolo26ObbTrainingPausedError()

    return Yolo26ObbTrainingLoopResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=checkpoint_bytes,
        metrics_history=metrics_history,
        validation_history=validation_history,
    )


def _run_yolo26_obb_epoch(
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
    device_name: str,
    epoch: int,
    max_epochs: int,
    global_iteration: int,
    augmentation_options: Any,
    assign_topk2: int | None,
    autocast_context: Callable[[], Any],
) -> tuple[dict[str, float], int]:
    """执行 YOLO26 OBB 单轮训练。"""

    epoch_losses: dict[str, float] = {}
    iteration_count = 0
    effective_augmentation_options = resolve_yolo26_task_augmentation_for_epoch(
        augmentation_options=augmentation_options,
        epoch_index=epoch,
        max_epochs=max_epochs,
    )
    shuffled = list(train_annotations)
    random.shuffle(shuffled)
    for batch_start in range(0, len(shuffled), batch_size):
        batch_annotations = shuffled[batch_start : batch_start + batch_size]
        batch_input_size = resolve_yolo26_task_batch_input_size(
            base_input_size=base_input_size,
            augmentation_options=effective_augmentation_options,
        )
        batch = build_yolo26_obb_training_batch(
            samples=batch_annotations,
            input_size=batch_input_size,
            device=device_name,
            precision=precision,
            imports=imports,
            augmentation_options=effective_augmentation_options,
            available_samples=shuffled,
        )
        if batch is None:
            continue
        with autocast_context():
            raw_outputs = model(batch.images)
            raw_for_loss = (
                raw_outputs["one2many"]
                if isinstance(raw_outputs, dict) and "one2many" in raw_outputs
                else raw_outputs
            )
            loss_payload = compute_yolo26_obb_loss(
                torch=imports.torch,
                model=model,
                raw_outputs=raw_for_loss,
                batch_targets=batch.targets,
                num_classes=0,
                assign_topk2=assign_topk2,
            )
        total_loss = loss_payload["loss"]
        if not total_loss.requires_grad:
            total_loss = _build_zero_grad_loss(raw_for_loss, imports.torch)
        optimizer.zero_grad()
        if scaler is not None:
            scaler.scale(total_loss).backward()
            scaler.unscale_(optimizer)
            imports.torch.nn.utils.clip_grad_norm_(trainable_parameters, 10.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            total_loss.backward()
            imports.torch.nn.utils.clip_grad_norm_(trainable_parameters, 10.0)
            optimizer.step()
        scheduler.step()
        global_iteration += 1
        iteration_count += 1
        for key, value in loss_payload.items():
            epoch_losses[key] = epoch_losses.get(key, 0.0) + float(value.item())

    divisor = max(1, iteration_count)
    return (
        {key: round(value / divisor, 6) for key, value in epoch_losses.items()}
        if epoch_losses
        else {"loss": 0.0},
        global_iteration,
    )


def _run_yolo26_obb_validation(
    *,
    imports: Any,
    model: Any,
    val_annotations: list[Any],
    labels: tuple[str, ...],
    input_size: tuple[int, int],
    device_name: str,
    precision: str,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
) -> dict[str, float]:
    """执行 YOLO26 OBB 训练期 validation。"""

    should_evaluate = (
        len(val_annotations) > 0 and epoch > 0 and epoch % evaluation_interval == 0
    ) or epoch == max_epochs - 1
    if not should_evaluate:
        return {}
    return evaluate_yolo26_obb_samples(
        model=model,
        samples=val_annotations,
        labels=labels,
        input_size=input_size,
        device=device_name,
        precision=precision,
        score_threshold=evaluation_confidence_threshold,
        nms_threshold=evaluation_nms_threshold,
        imports=imports,
    )


def _build_zero_grad_loss(raw_outputs: Any, torch_module: Any) -> Any:
    """用模型输出构建可反传的零损失。"""

    if torch_module.is_tensor(raw_outputs):
        return raw_outputs.sum() * 0.0
    if isinstance(raw_outputs, dict):
        tensors = [
            _build_zero_grad_loss(value, torch_module)
            for value in raw_outputs.values()
            if _contains_tensor(value, torch_module)
        ]
    elif isinstance(raw_outputs, list | tuple):
        tensors = [
            _build_zero_grad_loss(value, torch_module)
            for value in raw_outputs
            if _contains_tensor(value, torch_module)
        ]
    else:
        tensors = []
    if tensors:
        return sum(tensors)
    return torch_module.zeros((), requires_grad=True)


def _contains_tensor(value: Any, torch_module: Any) -> bool:
    """判断输出结构里是否包含 torch Tensor。"""

    if torch_module.is_tensor(value):
        return True
    if isinstance(value, dict):
        return any(_contains_tensor(item, torch_module) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_tensor(item, torch_module) for item in value)
    return False


__all__ = [
    "Yolo26ObbTrainingControlCommand",
    "Yolo26ObbTrainingEpochProgress",
    "Yolo26ObbTrainingLoopResult",
    "Yolo26ObbTrainingPausedError",
    "Yolo26ObbTrainingSavePoint",
    "Yolo26ObbTrainingTerminatedError",
    "run_yolo26_obb_training_loop",
]
