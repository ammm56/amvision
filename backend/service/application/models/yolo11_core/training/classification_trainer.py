"""YOLO11 classification 主训练循环。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo11_core.data import (
    build_yolo11_classification_training_batch,
)
from backend.service.application.models.yolo_core_common.data import (
    YoloClassificationAugmentationOptions,
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
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


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


@dataclass(frozen=True)
class Yolo11ClassificationTrainingLoopResult:
    """描述 YOLO11 classification 完整训练循环结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_history: list[dict[str, float]]
    validation_history: list[dict[str, float]]


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
    input_size: tuple[int, int],
    precision: str,
    device_name: str,
    augmentation_options: YoloClassificationAugmentationOptions | None,
    learning_rate: float,
    weight_decay: float,
    min_lr_ratio: float,
    start_epoch: int,
    global_iteration: int,
    metrics_history: list[dict[str, float]],
    validation_history: list[dict[str, float]],
    best_metric_value: float,
    best_metric_name: str,
    epoch_callback: Callable[
        [Yolo11ClassificationTrainingEpochProgress],
        Yolo11ClassificationTrainingControlCommand | None,
    ]
    | None = None,
    savepoint_callback: Callable[[Yolo11ClassificationTrainingSavePoint], None]
    | None = None,
) -> Yolo11ClassificationTrainingLoopResult:
    """执行 YOLO11 classification 从 start epoch 到 max epoch 的完整训练循环。"""

    checkpoint_bytes = b""
    for epoch in range(start_epoch, max_epochs):
        model.train()
        train_loss_sum = 0.0
        train_correct = 0
        train_total = 0
        for batch_start in range(0, len(train_annotations), batch_size):
            batch_annotations = train_annotations[
                batch_start : batch_start + batch_size
            ]
            batch = build_yolo11_classification_training_batch(
                samples=batch_annotations,
                input_size=input_size,
                device=device_name,
                precision=precision,
                imports=imports,
                augmentation_options=augmentation_options,
            )
            if batch is None:
                continue
            with autocast_context():
                outputs = model(batch.images)
                loss, probabilities = compute_yolo11_classification_loss(
                    torch_module=imports.torch,
                    outputs=outputs,
                    targets=batch.targets,
                )
            optimizer.zero_grad(set_to_none=True)
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
            else:
                loss.backward()
                optimizer.step()
            scheduler.step()
            _, predicted = imports.torch.max(probabilities, 1)
            train_correct += int((predicted == batch.targets).sum().item())
            train_total += int(batch.targets.size(0))
            train_loss_sum += float(loss.item()) * int(batch.targets.size(0))
            global_iteration += 1

        train_accuracy = train_correct / max(1, train_total)
        train_loss = train_loss_sum / max(1, train_total)
        epoch_metrics = {
            "loss": round(train_loss, 6),
            "accuracy": round(train_accuracy, 6),
        }
        metrics_history.append({"epoch": epoch, **epoch_metrics})
        epoch_progress = Yolo11ClassificationTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=epoch_metrics,
        )
        cmd = epoch_callback(epoch_progress) if epoch_callback is not None else None
        if cmd is not None and cmd.terminate_training:
            raise Yolo11ClassificationTrainingTerminatedError()

        val_metrics: dict[str, float] = {}
        should_evaluate = (
            len(val_annotations) > 0 and epoch > 0 and epoch % evaluation_interval == 0
        ) or epoch == max_epochs - 1
        if should_evaluate:
            val_metrics = evaluate_yolo11_classification_samples(
                model=model,
                samples=val_annotations,
                labels=labels,
                batch_size=batch_size,
                input_size=input_size,
                device=device_name,
                precision=precision,
                imports=imports,
            )
            validation_history.append({"epoch": epoch, **val_metrics})

        current_val_metric = float(val_metrics.get("top1_accuracy", 0.0))
        if current_val_metric > best_metric_value:
            best_metric_value = current_val_metric
            best_metric_name = "val_top1_accuracy"

        checkpoint_bytes = build_yolo11_classification_checkpoint_bytes(
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
            torch_module=imports.torch,
        )
        if cmd is not None and savepoint_callback is not None:
            savepoint_callback(
                Yolo11ClassificationTrainingSavePoint(
                    latest_checkpoint_bytes=checkpoint_bytes,
                    train_metrics=epoch_metrics,
                    validation_metrics=val_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )
        if cmd is not None and cmd.pause_training:
            raise Yolo11ClassificationTrainingPausedError()

    return Yolo11ClassificationTrainingLoopResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=checkpoint_bytes,
        metrics_history=metrics_history,
        validation_history=validation_history,
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
