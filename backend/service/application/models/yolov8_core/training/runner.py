"""YOLOv8 detection 单轮训练执行器。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)
from backend.service.application.models.training.training_engine import (
    record_active_training_batch_stage_metrics,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloDetectionLossAccumulator,
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
    normalize_yolo_detection_loss_metrics,
    resolve_yolo_optimizer_base_learning_rate,
    YoloTrainingNumericalError,
)
from backend.service.application.models.yolov8_core.training.pytorch_dataloader import (
    YoloV8DetectionDataLoaderBatch,
)


@dataclass(frozen=True)
class YoloV8DetectionTrainingBatchProgress:
    """描述 YOLOv8 detection 单个训练 batch 的进度。"""

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
class YoloV8DetectionTrainingEpochResult:
    """描述 YOLOv8 detection 单轮训练结果。"""

    global_iteration: int
    train_metrics: dict[str, float]
    successful_optimizer_steps: int
    skipped_optimizer_steps: int


def run_yolov8_detection_training_epoch(
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
    build_batch: Callable[
        [list[Any], tuple[Any, ...], int], tuple[Any, tuple[Any, ...]]
    ],
    unwrap_outputs: Callable[[Any], dict[str, Any]],
    compute_loss: Callable[..., dict[str, Any]],
    grad_clip_norm: float,
    ema: Any | None = None,
    dataloader_batches: Iterable[YoloV8DetectionDataLoaderBatch] | None = None,
    device: str | None = None,
    runtime_precision: str = "fp32",
    training_schedule: YoloUltralyticsTrainingSchedule | None = None,
    batch_callback: Callable[[YoloV8DetectionTrainingBatchProgress], None]
    | None = None,
) -> YoloV8DetectionTrainingEpochResult:
    """执行 YOLOv8 detection 一个 epoch 的 batch 循环。"""

    shuffled_samples = list(samples)
    available_samples = tuple(shuffled_samples)
    batch_iterator: Iterable[Any]
    if dataloader_batches is None:
        random.shuffle(shuffled_samples)
        available_samples = tuple(shuffled_samples)
        batch_iterator = _iter_yolov8_detection_batches(shuffled_samples, batch_size)
        max_iterations = max(1, (len(shuffled_samples) + batch_size - 1) // batch_size)
    else:
        batch_iterator = dataloader_batches
        max_iterations = max(1, _safe_len(dataloader_batches))
    epoch_losses = YoloDetectionLossAccumulator()
    model.train()
    optimizer.zero_grad(set_to_none=True)
    last_optimizer_step_iteration = 0
    successful_optimizer_steps = 0
    skipped_optimizer_steps = 0

    for iteration, sample_batch in enumerate(batch_iterator, start=1):
        global_iteration += 1
        current_accumulate = _resolve_yolov8_current_accumulate(
            optimizer=optimizer,
            training_schedule=training_schedule,
            global_iteration=global_iteration,
            epoch=epoch,
            batch_size=batch_size,
        )
        if isinstance(sample_batch, YoloV8DetectionDataLoaderBatch):
            resolved_device = device or "cpu"
            batch_images = sample_batch.images
            if not bool(torch_module.is_tensor(batch_images)):
                batch_images = torch_module.from_numpy(batch_images)
            images = move_yolo_tensor_to_training_device(
                batch_images,
                device=resolved_device,
                runtime_precision=runtime_precision,
            )
            batch_targets = sample_batch.targets
        else:
            images, batch_targets = build_batch(sample_batch, available_samples, epoch)
        progress_input_size = _read_yolov8_batch_input_size(
            images=images,
            fallback=input_size,
        )
        forward_started_at = time.perf_counter()
        with autocast_context():
            raw_outputs = unwrap_outputs(model(images))
            loss_components = compute_loss(
                model=model,
                raw_outputs=raw_outputs,
                batch_targets=batch_targets,
            )
            loss = loss_components["loss"]
        if not bool(torch_module.isfinite(loss.detach()).item()):
            raise YoloTrainingNumericalError(
                f"YOLOv8 detection loss 非有限 (global_iteration={global_iteration})"
            )
        backward_started_at = time.perf_counter()
        scaler.scale(loss).backward()
        should_step = (
            iteration - last_optimizer_step_iteration >= current_accumulate
            or iteration == max_iterations
        )
        if should_step:
            scaler.unscale_(optimizer)
            gradient_norm = torch_module.nn.utils.clip_grad_norm_(
                model.parameters(),
                grad_clip_norm if grad_clip_norm > 0 else float("inf"),
                error_if_nonfinite=False,
            )
            gradients_are_finite = bool(torch_module.isfinite(gradient_norm).item())
            scale_reader = getattr(scaler, "get_scale", None)
            scale_before = float(scale_reader()) if callable(scale_reader) else None
            scaler.step(optimizer)
            scaler.update()
            scale_after = float(scale_reader()) if callable(scale_reader) else None
            step_succeeded = gradients_are_finite and (
                scale_before is None
                or scale_after is None
                or scale_after >= scale_before
            )
            if step_succeeded:
                successful_optimizer_steps += 1
            else:
                skipped_optimizer_steps += 1
            if ema is not None and step_succeeded:
                ema.update(model)
            optimizer.zero_grad(set_to_none=True)
            last_optimizer_step_iteration = iteration
        completed_at = time.perf_counter()
        record_active_training_batch_stage_metrics(
            {
                "forward_loss_host_time_ms": (backward_started_at - forward_started_at)
                * 1000.0,
                "backward_optimizer_host_time_ms": (completed_at - backward_started_at)
                * 1000.0,
                "batch_compute_host_time_ms": (completed_at - forward_started_at)
                * 1000.0,
            }
        )

        reported_metrics = normalize_yolo_detection_loss_metrics(
            loss_components=loss_components,
            batch_sample_count=len(batch_targets),
        )
        epoch_losses.add(
            metrics=reported_metrics,
            batch_sample_count=len(batch_targets),
        )

        if batch_callback is not None:
            batch_callback(
                YoloV8DetectionTrainingBatchProgress(
                    epoch=epoch,
                    max_epochs=max_epochs,
                    iteration=iteration,
                    max_iterations=max_iterations,
                    global_iteration=global_iteration,
                    total_iterations=total_iterations,
                    input_size=progress_input_size,
                    learning_rate=(
                        resolve_yolo_optimizer_base_learning_rate(
                            optimizer=optimizer,
                            initial_learning_rate=training_schedule.initial_lr,
                        )
                        if training_schedule is not None
                        else float(optimizer.param_groups[0]["lr"])
                    ),
                    train_metrics=dict(reported_metrics),
                )
            )

    return YoloV8DetectionTrainingEpochResult(
        global_iteration=global_iteration,
        train_metrics=epoch_losses.mean(),
        successful_optimizer_steps=successful_optimizer_steps,
        skipped_optimizer_steps=skipped_optimizer_steps,
    )


def _iter_yolov8_detection_batches(
    samples: list[Any],
    batch_size: int,
) -> list[list[Any]]:
    """把样本列表切成 YOLOv8 detection 训练 batch。"""

    resolved_batch_size = max(1, int(batch_size))
    return [
        samples[start : start + resolved_batch_size]
        for start in range(0, len(samples), resolved_batch_size)
    ]


def _safe_len(value: Any) -> int:
    """读取 DataLoader batch 数量，读取失败时使用 1 兜底。"""

    try:
        return int(len(value))
    except TypeError:
        return 1


def _resolve_yolov8_current_accumulate(
    *,
    optimizer: Any,
    training_schedule: YoloUltralyticsTrainingSchedule | None,
    global_iteration: int,
    epoch: int,
    batch_size: int,
) -> int:
    """解析 YOLOv8 detection 当前 batch 使用的梯度累积步数。"""

    if training_schedule is None:
        return 1
    return apply_yolo_ultralytics_warmup(
        optimizer=optimizer,
        schedule=training_schedule,
        iteration_index=max(0, int(global_iteration) - 1),
        epoch=epoch,
        batch_size=batch_size,
    )


def _read_yolov8_batch_input_size(
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
    "YoloV8DetectionTrainingBatchProgress",
    "YoloV8DetectionTrainingEpochResult",
    "run_yolov8_detection_training_epoch",
]
