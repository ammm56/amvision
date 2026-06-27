"""YOLO26 detection 单轮训练执行器。"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo_core_common.training import (
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
)


@dataclass(frozen=True)
class Yolo26DetectionTrainingBatchProgress:
    """描述 YOLO26 detection 单个训练 batch 的进度。"""

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
class Yolo26DetectionTrainingEpochResult:
    """描述 YOLO26 detection 单轮训练结果。"""

    global_iteration: int
    train_metrics: dict[str, float]


def run_yolo26_detection_training_epoch(
    *,
    torch_module: Any,
    model: Any,
    samples: tuple[Any, ...],
    batch_size: int,
    input_size: tuple[int, int],
    epoch: int,
    max_epochs: int,
    global_iteration: int,
    total_iterations: int,
    optimizer: Any,
    scaler: Any,
    autocast_context: Callable[[], Any],
    build_batch: Callable[[list[Any], tuple[Any, ...], int], tuple[Any, tuple[Any, ...]]],
    unwrap_outputs: Callable[[Any], dict[str, Any]],
    compute_loss: Callable[..., dict[str, Any]],
    grad_clip_norm: float,
    ema: Any | None = None,
    training_schedule: YoloUltralyticsTrainingSchedule | None = None,
    batch_callback: Callable[[Yolo26DetectionTrainingBatchProgress], None]
    | None = None,
) -> Yolo26DetectionTrainingEpochResult:
    """执行 YOLO26 detection 一个 epoch 的 batch 循环。"""

    shuffled_samples = list(samples)
    random.shuffle(shuffled_samples)
    available_samples = tuple(shuffled_samples)
    max_iterations = max(1, (len(shuffled_samples) + batch_size - 1) // batch_size)
    epoch_losses = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
    model.train()
    optimizer.zero_grad(set_to_none=True)
    last_optimizer_step_iteration = 0

    for iteration, sample_batch in enumerate(
        _iter_yolo26_detection_batches(shuffled_samples, batch_size),
        start=1,
    ):
        global_iteration += 1
        current_accumulate = _resolve_yolo26_current_accumulate(
            optimizer=optimizer,
            training_schedule=training_schedule,
            global_iteration=global_iteration,
            epoch=epoch,
            batch_size=batch_size,
        )
        images, batch_targets = build_batch(sample_batch, available_samples, epoch)
        progress_input_size = _read_yolo26_batch_input_size(
            images=images,
            fallback=input_size,
        )
        with autocast_context():
            raw_outputs = unwrap_outputs(model(images))
            loss_components = compute_loss(
                model=model,
                raw_outputs=raw_outputs,
                batch_targets=batch_targets,
                epoch=epoch,
                max_epochs=max_epochs,
            )
            loss = loss_components["loss"]
        scaler.scale(loss).backward()
        should_step = (
            iteration - last_optimizer_step_iteration >= current_accumulate
            or iteration == max_iterations
        )
        if should_step:
            scaler.unscale_(optimizer)
            if grad_clip_norm > 0:
                torch_module.nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm)
            scaler.step(optimizer)
            scaler.update()
            if ema is not None:
                ema.update(model)
            optimizer.zero_grad(set_to_none=True)
            last_optimizer_step_iteration = iteration

        for metric_name in epoch_losses:
            epoch_losses[metric_name] += float(
                loss_components[metric_name].detach().item()
            )

        if batch_callback is not None:
            batch_callback(
                Yolo26DetectionTrainingBatchProgress(
                    epoch=epoch,
                    max_epochs=max_epochs,
                    iteration=iteration,
                    max_iterations=max_iterations,
                    global_iteration=global_iteration,
                    total_iterations=total_iterations,
                    input_size=progress_input_size,
                    learning_rate=float(optimizer.param_groups[0]["lr"]),
                    train_metrics={
                        "loss": float(loss_components["loss"].detach().item()),
                        "class_loss": float(
                            loss_components["class_loss"].detach().item()
                        ),
                        "box_loss": float(loss_components["box_loss"].detach().item()),
                        "dfl_loss": float(loss_components["dfl_loss"].detach().item()),
                    },
                )
            )

    return Yolo26DetectionTrainingEpochResult(
        global_iteration=global_iteration,
        train_metrics={
            metric_name: round(metric_total / max_iterations, 6)
            for metric_name, metric_total in epoch_losses.items()
        },
    )


def _iter_yolo26_detection_batches(
    samples: list[Any],
    batch_size: int,
) -> list[list[Any]]:
    """把样本列表切成 YOLO26 detection 训练 batch。"""

    resolved_batch_size = max(1, int(batch_size))
    return [
        samples[start : start + resolved_batch_size]
        for start in range(0, len(samples), resolved_batch_size)
    ]


def _resolve_yolo26_current_accumulate(
    *,
    optimizer: Any,
    training_schedule: YoloUltralyticsTrainingSchedule | None,
    global_iteration: int,
    epoch: int,
    batch_size: int,
) -> int:
    """解析 YOLO26 detection 当前 batch 使用的梯度累积步数。"""

    if training_schedule is None:
        return 1
    return apply_yolo_ultralytics_warmup(
        optimizer=optimizer,
        schedule=training_schedule,
        iteration_index=max(0, int(global_iteration) - 1),
        epoch=epoch,
        batch_size=batch_size,
    )


def _read_yolo26_batch_input_size(
    *,
    images: Any,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    """从 batch tensor 读取当前真实输入尺寸，读取失败时使用基础尺寸。"""

    shape = getattr(images, "shape", None)
    if shape is None or len(shape) < 4:
        return fallback
    return (int(shape[-2]), int(shape[-1]))


__all__ = [
    "Yolo26DetectionTrainingBatchProgress",
    "Yolo26DetectionTrainingEpochResult",
    "run_yolo26_detection_training_epoch",
]
