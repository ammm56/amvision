"""YOLO11 classification 主训练循环。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.training.metric_policy import (
    is_better_training_metric,
)
from backend.service.application.models.training.checkpoint_policy import (
    resolve_training_checkpoint_decision,
)

from backend.service.application.models.yolo11_core.data import (
    build_yolo11_classification_training_batch,
)
from backend.service.application.models.yolo_core_common.data import (
    YoloClassificationAugmentationOptions,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloClassificationDataLoaderPlan,
    YoloTaskTrainingBatchProgress,
    YoloTaskTrainingDataLoaderLifecycle,
    build_yolo_epoch_history_item,
    YoloUltralyticsOptimizerStep,
    YoloUltralyticsTrainingSchedule,
    build_yolo_classification_training_dataloader,
    load_yolo_classification_dataloader_imports,
    move_yolo_classification_batch_to_device,
    replace_yolo_classification_dataloader_plan_seed,
    resolve_yolo_classification_dataloader_plan,
    should_run_yolo_validation,
)
from backend.service.application.models.yolo11_core.evaluation import (
    evaluate_yolo11_classification_samples,
)
from backend.service.application.models.yolo11_core.losses import (
    compute_yolo11_classification_loss,
)
from backend.service.application.models.yolo11_core.training.classification_checkpoint import (
    build_yolo11_classification_checkpoint_bytes,
)


@dataclass(frozen=True)
class Yolo11ClassificationTrainingEpochProgress:
    """描述 YOLO11 classification 单轮训练进度。"""

    epoch: int
    max_epochs: int
    evaluation_interval: int
    validation_ran: bool
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_metrics_snapshot: dict[str, object]
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float


@dataclass(frozen=True)
class Yolo11ClassificationTrainingControlCommand:
    """描述 YOLO11 classification 训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class Yolo11ClassificationTrainingSavePoint:
    """描述 YOLO11 classification 训练过程中的保存点。"""

    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float
    is_best: bool = False


@dataclass(frozen=True)
class Yolo11ClassificationTrainingLoopResult:
    """描述 YOLO11 classification 完整训练循环结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_history: list[dict[str, float]]
    validation_history: list[dict[str, float]]
    best_checkpoint_bytes: bytes | None = None


class Yolo11ClassificationTrainingPausedError(Exception):
    """表示 YOLO11 classification 训练在 epoch 边界暂停。"""


class Yolo11ClassificationTrainingTerminatedError(Exception):
    """表示 YOLO11 classification 训练在 epoch 边界终止。"""


def run_yolo11_classification_training_loop(
    *,
    imports: Any,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
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
    augmentation_options: YoloClassificationAugmentationOptions | None,
    dataloader_plan: YoloClassificationDataLoaderPlan | None,
    learning_rate: float,
    weight_decay: float,
    min_lr_ratio: float,
    start_epoch: int,
    global_iteration: int,
    metrics_history: list[dict[str, float]],
    validation_history: list[dict[str, float]],
    best_metric_value: float,
    best_metric_name: str,
    training_schedule: YoloUltralyticsTrainingSchedule,
    ema: Any,
    grad_clip_norm: float = 10.0,
    epoch_callback: Callable[
        [Yolo11ClassificationTrainingEpochProgress],
        Yolo11ClassificationTrainingControlCommand | None,
    ]
    | None = None,
    savepoint_callback: Callable[[Yolo11ClassificationTrainingSavePoint], None]
    | None = None,
    batch_callback: Callable[[YoloTaskTrainingBatchProgress], None] | None = None,
    control_callback: Callable[[], None] | None = None,
) -> Yolo11ClassificationTrainingLoopResult:
    """执行 YOLO11 classification 从 start epoch 到 max epoch 的完整训练循环。"""

    checkpoint_bytes = b""
    best_checkpoint_bytes = b""
    resolved_dataloader_plan = (
        dataloader_plan
        or resolve_yolo_classification_dataloader_plan(
            extra_options={},
            device=device_name,
        )
    )
    optimizer_step = YoloUltralyticsOptimizerStep(
        torch_module=imports.torch,
        model=model,
        optimizer=optimizer,
        scaler=scaler,
        schedule=training_schedule,
        ema=ema,
        grad_clip_norm=grad_clip_norm,
        initial_iteration=global_iteration,
    )
    training_loader_lifecycle = YoloTaskTrainingDataLoaderLifecycle()
    for epoch in range(start_epoch, max_epochs):
        model.train()
        train_loss_sum = 0.0
        train_correct = 0
        train_total = 0
        train_dataloader = training_loader_lifecycle.resolve(
            augmentation_options=augmentation_options,
            build_loader=lambda: build_yolo_classification_training_dataloader(
                torch_module=imports.torch,
                samples=train_annotations,
                batch_size=batch_size,
                input_size=input_size,
                training=True,
                augmentation_options=augmentation_options,
                plan=resolved_dataloader_plan,
                shuffle=True,
                build_batch=build_yolo11_classification_training_batch,
                load_imports=load_yolo_classification_dataloader_imports,
            ),
        )
        max_iterations = max(1, len(train_dataloader))
        for iteration, cpu_batch in enumerate(train_dataloader, start=1):
            if control_callback is not None:
                control_callback()
            if cpu_batch is None:
                continue
            batch = move_yolo_classification_batch_to_device(
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
                batch_size=int(batch.targets.size(0)),
            )
            with autocast_context():
                outputs = model(batch.images)
                loss, probabilities = compute_yolo11_classification_loss(
                    torch_module=imports.torch,
                    outputs=outputs,
                    targets=batch.targets,
                )
            optimizer_step.backward_and_step(
                loss=loss,
                iteration_index=global_iteration,
                is_last_batch=(
                    epoch + 1 == max_epochs and iteration == max_iterations
                ),
            )
            _, predicted = imports.torch.max(probabilities, 1)
            train_correct += int((predicted == batch.targets).sum().item())
            train_total += int(batch.targets.size(0))
            train_loss_sum += float(loss.item()) * int(batch.targets.size(0))
            if batch_callback is not None:
                batch_count = max(1, int(batch.targets.size(0)))
                batch_callback(
                    YoloTaskTrainingBatchProgress(
                        epoch=epoch,
                        max_epochs=max_epochs,
                        iteration=iteration,
                        max_iterations=max_iterations,
                        global_iteration=global_iteration,
                        total_iterations=max_epochs * max_iterations,
                        input_size=input_size,
                        learning_rate=float(scheduler.get_last_lr()[0]),
                        train_metrics={
                            "loss": round(float(loss.item()), 6),
                            "accuracy": round(
                                float((predicted == batch.targets).sum().item())
                                / batch_count,
                                6,
                            ),
                        },
                    )
                )

        train_accuracy = train_correct / max(1, train_total)
        train_loss = train_loss_sum / max(1, train_total)
        epoch_metrics = {
            "loss": round(train_loss, 6),
            "accuracy": round(train_accuracy, 6),
        }
        metrics_history.append(
            build_yolo_epoch_history_item(epoch_index=epoch, metrics=epoch_metrics)
        )
        val_metrics: dict[str, float] = {}
        should_evaluate = should_run_yolo_validation(
            epoch_index=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            has_validation_samples=bool(val_annotations),
        )
        if should_evaluate:
            val_metrics = evaluate_yolo11_classification_samples(
                model=ema.model,
                samples=val_annotations,
                labels=labels,
                batch_size=batch_size,
                input_size=input_size,
                device=device_name,
                precision=precision,
                imports=imports,
                dataloader_plan=replace_yolo_classification_dataloader_plan_seed(
                    plan=resolved_dataloader_plan,
                    seed=100_000 + epoch,
                ),
                control_callback=control_callback,
            )
            validation_history.append(
                build_yolo_epoch_history_item(epoch_index=epoch, metrics=val_metrics)
            )

        current_val_metric = float(val_metrics.get("top1_accuracy", 0.0))
        current_metric_value = current_val_metric if should_evaluate else None
        best_metric_improved = (
            should_evaluate
            and is_better_training_metric(
                current_value=current_val_metric,
                best_value=best_metric_value,
                direction="maximize",
                maximum=1.0,
            )
        )
        if best_metric_improved:
            best_metric_value = current_val_metric
            best_metric_name = "val_top1_accuracy"

        optimizer_step.step_scheduler_if_optimizer_updated(scheduler)
        epoch_progress = Yolo11ClassificationTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            validation_ran=should_evaluate,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=dict(metrics_history[-1]),
            validation_metrics=(
                dict(validation_history[-1]) if val_metrics else {}
            ),
            train_metrics_snapshot={
                "final_metrics": metrics_history[-1] if metrics_history else {},
                "epoch_history": [dict(item) for item in metrics_history],
                "scheduler": "LambdaLR",
                "optimizer": training_schedule.optimizer_name,
                "accumulate": training_schedule.accumulate,
                "scaled_weight_decay": training_schedule.scaled_weight_decay,
            },
            validation_metrics_snapshot={
                "final_metrics": validation_history[-1] if validation_history else {},
                "epoch_history": [dict(item) for item in validation_history],
            },
            current_metric_name=best_metric_name,
            current_metric_value=current_metric_value,
            best_metric_name=best_metric_name,
            best_metric_value=best_metric_value,
        )
        cmd = epoch_callback(epoch_progress) if epoch_callback is not None else None
        checkpoint_decision = resolve_training_checkpoint_decision(
            completed_epoch=epoch + 1,
            max_epochs=max_epochs,
            interval_epochs=checkpoint_interval,
            best_improved=best_metric_improved,
            manual_save_requested=bool(cmd and cmd.save_checkpoint),
            pause_requested=bool(cmd and cmd.pause_training),
            terminate_requested=bool(cmd and cmd.terminate_training),
        )
        if checkpoint_decision.should_serialize:
            checkpoint_bytes = build_yolo11_classification_checkpoint_bytes(
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
                torch_module=imports.torch,
            )
        if best_metric_improved and checkpoint_decision.should_serialize:
            best_checkpoint_bytes = checkpoint_bytes
        if checkpoint_decision.should_serialize and savepoint_callback is not None:
            savepoint_callback(
                Yolo11ClassificationTrainingSavePoint(
                    latest_checkpoint_bytes=checkpoint_bytes,
                    train_metrics=epoch_progress.train_metrics,
                    validation_metrics=epoch_progress.validation_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                    is_best=best_metric_improved,
                )
            )
        if cmd is not None and cmd.pause_training:
            raise Yolo11ClassificationTrainingPausedError()
        if cmd is not None and cmd.terminate_training:
            raise Yolo11ClassificationTrainingTerminatedError()

    training_loader_lifecycle.close()
    return Yolo11ClassificationTrainingLoopResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=checkpoint_bytes,
        metrics_history=metrics_history,
        validation_history=validation_history,
        best_checkpoint_bytes=best_checkpoint_bytes or None,
    )


__all__ = [
    "Yolo11ClassificationTrainingControlCommand",
    "Yolo11ClassificationTrainingEpochProgress",
    "Yolo11ClassificationTrainingLoopResult",
    "Yolo11ClassificationTrainingPausedError",
    "Yolo11ClassificationTrainingSavePoint",
    "Yolo11ClassificationTrainingTerminatedError",
    "run_yolo11_classification_training_loop",
]
