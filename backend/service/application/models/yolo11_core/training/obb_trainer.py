"""YOLO11 OBB 主训练循环。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.training.metric_policy import (
    is_better_training_metric,
)
from backend.service.application.models.training.checkpoint_policy import (
    resolve_training_checkpoint_persistence_decision,
)

from backend.service.application.models.yolo_core_common.training import (
    YoloTaskDataLoaderPlan,
    YoloTaskTrainingBatchProgress,
    YoloTaskTrainingDataLoaderLifecycle,
    build_yolo_epoch_history_item,
    YoloUltralyticsOptimizerStep,
    YoloUltralyticsTrainingSchedule,
    build_yolo_task_training_dataloader,
    load_yolo_task_dataloader_imports,
    move_yolo_task_batch_to_device,
    resolve_yolo_optimizer_base_learning_rate,
    resolve_yolo_task_dataloader_plan,
    should_run_yolo_validation,
)
from backend.service.application.models.yolo11_core.data import (
    build_yolo11_obb_training_batch,
    resolve_yolo11_task_augmentation_for_epoch,
    resolve_yolo11_task_batch_input_size,
)
from backend.service.application.models.yolo11_core.evaluation import (
    evaluate_yolo11_obb_samples,
)
from backend.service.application.models.yolo11_core.losses import (
    compute_yolo11_obb_loss,
)
from backend.service.application.models.yolo11_core.training.obb_checkpoint import (
    build_yolo11_obb_checkpoint_bytes,
)


@dataclass(frozen=True)
class Yolo11ObbTrainingEpochProgress:
    """描述 YOLO11 OBB 单轮训练进度。"""

    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float] | None = None
    best_metric_value: float | None = None
    best_metric_name: str | None = None


@dataclass(frozen=True)
class Yolo11ObbTrainingControlCommand:
    """描述 YOLO11 OBB 训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class Yolo11ObbTrainingSavePoint:
    """描述 YOLO11 OBB 训练保存点。"""

    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float
    is_best: bool = False


@dataclass(frozen=True)
class Yolo11ObbTrainingLoopResult:
    """描述 YOLO11 OBB 完整训练循环结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes
    metrics_history: list[dict[str, float]]
    validation_history: list[dict[str, float]]


class Yolo11ObbTrainingPausedError(Exception):
    """表示 YOLO11 OBB 训练在 epoch 边界暂停。"""


class Yolo11ObbTrainingTerminatedError(Exception):
    """表示 YOLO11 OBB 训练在 epoch 边界终止。"""


def run_yolo11_obb_training_loop(
    *,
    imports: Any,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
    training_schedule: YoloUltralyticsTrainingSchedule,
    ema: Any,
    autocast_context: Callable[[], Any],
    labels: tuple[str, ...],
    train_annotations: list[Any],
    val_annotations: list[Any],
    batch_size: int,
    max_epochs: int,
    evaluation_interval: int,
    checkpoint_interval: int = 5,
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
    previous_best_checkpoint_bytes: bytes = b"",
    epoch_callback: Callable[
        [Yolo11ObbTrainingEpochProgress],
        Yolo11ObbTrainingControlCommand | None,
    ]
    | None = None,
    batch_callback: Callable[[YoloTaskTrainingBatchProgress], None] | None = None,
    savepoint_callback: Callable[[Yolo11ObbTrainingSavePoint], None] | None = None,
    control_callback: Callable[[], Yolo11ObbTrainingControlCommand | None]
    | None = None,
    dataloader_plan: YoloTaskDataLoaderPlan | None = None,
) -> Yolo11ObbTrainingLoopResult:
    """执行 YOLO11 OBB 从 start epoch 到 max epoch 的完整训练循环。"""

    checkpoint_bytes = build_yolo11_obb_checkpoint_bytes(
        epoch=start_epoch - 1,
        global_iteration=global_iteration,
        model=model,
        ema_model=ema.model,
        ema_updates=ema.updates,
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
    best_checkpoint_bytes = previous_best_checkpoint_bytes
    last_completed_savepoint = Yolo11ObbTrainingSavePoint(
        latest_checkpoint_bytes=checkpoint_bytes,
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

        if control_callback is None:
            return
        command = control_callback()
        if command is None:
            return
        if (
            command.save_checkpoint
            or command.pause_training
            or command.terminate_training
        ) and savepoint_callback is not None:
            savepoint_callback(last_completed_savepoint)
        if command.pause_training:
            raise Yolo11ObbTrainingPausedError()
        if command.terminate_training:
            raise Yolo11ObbTrainingTerminatedError()
    resolved_dataloader_plan = dataloader_plan or resolve_yolo_task_dataloader_plan(
        extra_options={},
        device=device_name,
    )
    optimizer_step = YoloUltralyticsOptimizerStep(
        torch_module=imports.torch,
        model=model,
        optimizer=optimizer,
        scaler=scaler,
        schedule=training_schedule,
        ema=ema,
        grad_clip_norm=10.0,
        initial_iteration=global_iteration,
    )
    training_loader_lifecycle = YoloTaskTrainingDataLoaderLifecycle()
    for epoch in range(start_epoch, max_epochs):
        model.train()
        effective_augmentation_options = resolve_yolo11_task_augmentation_for_epoch(
            augmentation_options=augmentation_options,
            epoch_index=epoch,
            max_epochs=max_epochs,
        )
        train_dataloader = training_loader_lifecycle.resolve(
            augmentation_options=effective_augmentation_options,
            build_loader=lambda: build_yolo_task_training_dataloader(
                torch_module=imports.torch,
                samples=train_annotations,
                batch_size=batch_size,
                input_size=input_size,
                training=True,
                augmentation_options=effective_augmentation_options,
                plan=resolved_dataloader_plan,
                shuffle=True,
                build_batch=build_yolo11_obb_training_batch,
                load_imports=load_yolo_task_dataloader_imports,
                resolve_batch_input_size=resolve_yolo11_task_batch_input_size,
            ),
        )
        epoch_metrics, global_iteration = _run_yolo11_obb_epoch(
            imports=imports,
            model=model,
            optimizer=optimizer,
            scaler=scaler,
            optimizer_step=optimizer_step,
            train_dataloader=train_dataloader,
            precision=precision,
            device_name=device_name,
            epoch=epoch,
            max_epochs=max_epochs,
            global_iteration=global_iteration,
            assign_topk2=assign_topk2,
            autocast_context=autocast_context,
            control_callback=observe_control,
            input_size=input_size,
            learning_rate=resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            batch_callback=batch_callback,
        )
        metrics_history.append(
            build_yolo_epoch_history_item(epoch_index=epoch, metrics=epoch_metrics)
        )
        validation_metrics = _run_yolo11_obb_validation(
            imports=imports,
            model=ema.model,
            val_annotations=val_annotations,
            labels=labels,
            input_size=input_size,
            device_name=device_name,
            precision=precision,
            evaluation_confidence_threshold=evaluation_confidence_threshold,
            evaluation_nms_threshold=evaluation_nms_threshold,
            batch_size=batch_size,
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            control_callback=observe_control,
        )
        if validation_metrics:
            validation_history.append(
                build_yolo_epoch_history_item(
                    epoch_index=epoch,
                    metrics=validation_metrics,
                )
            )
        current_metric = float(validation_metrics.get("map50_95", 0.0))
        best_metric_improved = bool(validation_metrics) and is_better_training_metric(
            current_value=current_metric,
            best_value=best_metric_value,
            direction="maximize",
            maximum=1.0,
        )
        if best_metric_improved:
            best_metric_value = current_metric
            best_metric_name = "val_map50_95"

        optimizer_step.step_scheduler_if_optimizer_updated(scheduler)
        epoch_progress = Yolo11ObbTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            input_size=input_size,
            learning_rate=resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            train_metrics=epoch_metrics,
            validation_metrics=validation_metrics or None,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
        )
        command = epoch_callback(epoch_progress) if epoch_callback is not None else None
        checkpoint_decision = resolve_training_checkpoint_persistence_decision(
            completed_epoch=epoch + 1,
            max_epochs=max_epochs,
            interval_epochs=checkpoint_interval,
            best_improved=best_metric_improved,
            manual_save_requested=bool(command and command.save_checkpoint),
            pause_requested=bool(command and command.pause_training),
            terminate_requested=bool(command and command.terminate_training),
        )
        checkpoint_bytes = build_yolo11_obb_checkpoint_bytes(
                epoch=epoch,
                global_iteration=global_iteration,
                model=model,
                ema_model=ema.model,
                ema_updates=ema.updates,
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
        if best_metric_improved:
            best_checkpoint_bytes = checkpoint_bytes
        last_completed_savepoint = Yolo11ObbTrainingSavePoint(
            latest_checkpoint_bytes=checkpoint_bytes,
            train_metrics=epoch_metrics,
            validation_metrics=validation_metrics,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            epoch=epoch + 1,
            learning_rate=resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            is_best=best_metric_improved,
        )
        if checkpoint_decision.should_persist and savepoint_callback is not None:
            savepoint_callback(last_completed_savepoint)
        if command is not None and command.pause_training:
            raise Yolo11ObbTrainingPausedError()
        if command is not None and command.terminate_training:
            raise Yolo11ObbTrainingTerminatedError()

    training_loader_lifecycle.close()
    if not best_checkpoint_bytes:
        best_checkpoint_bytes = checkpoint_bytes
    return Yolo11ObbTrainingLoopResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=checkpoint_bytes,
        best_checkpoint_bytes=best_checkpoint_bytes,
        metrics_history=metrics_history,
        validation_history=validation_history,
    )


def _run_yolo11_obb_epoch(
    *,
    imports: Any,
    model: Any,
    optimizer: Any,
    scaler: Any | None,
    optimizer_step: YoloUltralyticsOptimizerStep,
    train_dataloader: Any,
    precision: str,
    device_name: str,
    epoch: int,
    max_epochs: int,
    global_iteration: int,
    assign_topk2: int | None,
    autocast_context: Callable[[], Any],
    control_callback: Callable[[], None] | None,
    input_size: tuple[int, int],
    learning_rate: float,
    batch_callback: Callable[[YoloTaskTrainingBatchProgress], None] | None,
) -> tuple[dict[str, float], int]:
    """执行 YOLO11 OBB 单轮训练。"""

    epoch_losses: dict[str, float] = {}
    sample_count = 0
    max_iterations = max(1, len(train_dataloader))
    for iteration, cpu_batch in enumerate(train_dataloader, start=1):
        if control_callback is not None:
            control_callback()
        if cpu_batch is None:
            continue
        batch = move_yolo_task_batch_to_device(
            batch=cpu_batch,
            device=device_name,
            precision=precision,
            torch_module=imports.torch,
        )
        if batch is None:
            continue
        global_iteration += 1
        optimizer_step.prepare_batch(
            iteration_index=global_iteration,
            epoch=epoch + 1,
            batch_size=len(batch.targets),
        )
        with autocast_context():
            raw_outputs = model(batch.images)
            raw_for_loss = (
                raw_outputs["one2many"]
                if isinstance(raw_outputs, dict) and "one2many" in raw_outputs
                else raw_outputs
            )
            loss_payload = compute_yolo11_obb_loss(
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
        optimizer_step.backward_and_step(
            loss=total_loss,
            iteration_index=global_iteration,
            is_last_batch=epoch + 1 == max_epochs and iteration == max_iterations,
        )
        batch_sample_count = len(batch.targets)
        for key, value in loss_payload.items():
            metric_value = float(value.item())
            if key == "loss":
                metric_value /= batch_sample_count
            epoch_losses[key] = (
                epoch_losses.get(key, 0.0) + metric_value * batch_sample_count
            )
        sample_count += batch_sample_count
        if batch_callback is not None:
            batch_metrics: dict[str, float] = {}
            for name, value in loss_payload.items():
                metric_value = float(value.item())
                if name == "loss":
                    metric_value /= max(1, batch_sample_count)
                batch_metrics[name] = round(metric_value, 6)
            batch_callback(
                YoloTaskTrainingBatchProgress(
                    epoch=epoch,
                    max_epochs=max_epochs,
                    iteration=iteration,
                    max_iterations=max_iterations,
                    global_iteration=global_iteration,
                    total_iterations=max_epochs * max_iterations,
                    input_size=input_size,
                    learning_rate=learning_rate,
                    train_metrics=batch_metrics,
                )
            )

    divisor = max(1, sample_count)
    return (
        {key: round(value / divisor, 6) for key, value in epoch_losses.items()}
        if epoch_losses
        else {"loss": 0.0},
        global_iteration,
    )


def _run_yolo11_obb_validation(
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
    batch_size: int,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
    control_callback: Callable[[], None] | None,
) -> dict[str, float]:
    """执行 YOLO11 OBB 训练期 validation。"""

    should_evaluate = should_run_yolo_validation(
        epoch_index=epoch,
        max_epochs=max_epochs,
        evaluation_interval=evaluation_interval,
        has_validation_samples=bool(val_annotations),
    )
    if not should_evaluate:
        return {}
    return evaluate_yolo11_obb_samples(
        model=model,
        samples=val_annotations,
        labels=labels,
        input_size=input_size,
        device=device_name,
        precision=precision,
        score_threshold=evaluation_confidence_threshold,
        nms_threshold=evaluation_nms_threshold,
        imports=imports,
        batch_size=batch_size,
        control_callback=control_callback,
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
    "Yolo11ObbTrainingControlCommand",
    "Yolo11ObbTrainingEpochProgress",
    "Yolo11ObbTrainingLoopResult",
    "Yolo11ObbTrainingPausedError",
    "Yolo11ObbTrainingSavePoint",
    "Yolo11ObbTrainingTerminatedError",
    "run_yolo11_obb_training_loop",
]
