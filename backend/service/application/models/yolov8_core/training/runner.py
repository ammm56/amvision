"""YOLOv8 detection 单轮训练执行器。"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.support.distributed_training import (
    DdpTrainingContext,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloUltralyticsTrainingSchedule,
    apply_yolo_ultralytics_warmup,
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


def run_yolov8_detection_training_epoch(
    *,
    torch_module: Any,
    model: Any,
    loss_model: Any | None = None,
    ema_model: Any | None = None,
    gradient_model: Any | None = None,
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
    ddp_context: DdpTrainingContext | None = None,
    batch_callback: Callable[[YoloV8DetectionTrainingBatchProgress], None] | None = None,
) -> YoloV8DetectionTrainingEpochResult:
    """执行 YOLOv8 detection 一个 epoch 的 batch 循环。"""

    resolved_loss_model = loss_model if loss_model is not None else model
    resolved_ema_model = ema_model if ema_model is not None else resolved_loss_model
    resolved_gradient_model = (
        gradient_model if gradient_model is not None else resolved_loss_model
    )
    epoch_samples = _resolve_yolov8_detection_epoch_samples(
        torch_module=torch_module,
        samples=samples,
        epoch=epoch,
        ddp_context=ddp_context,
    )
    available_samples = tuple(samples if ddp_context is not None else epoch_samples)
    max_iterations = max(1, (len(epoch_samples) + batch_size - 1) // batch_size)
    epoch_losses = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
    model.train()
    optimizer.zero_grad(set_to_none=True)
    last_optimizer_step_iteration = 0

    for iteration, sample_batch in enumerate(
        _iter_yolov8_detection_batches(epoch_samples, batch_size),
        start=1,
    ):
        global_iteration += 1
        current_accumulate = _resolve_yolov8_current_accumulate(
            optimizer=optimizer,
            training_schedule=training_schedule,
            global_iteration=global_iteration,
            epoch=epoch,
            batch_size=batch_size,
        )
        images, batch_targets = build_batch(sample_batch, available_samples, epoch)
        progress_input_size = _read_yolov8_batch_input_size(
            images=images,
            fallback=input_size,
        )
        with autocast_context():
            raw_outputs = unwrap_outputs(model(images))
            loss_components = compute_loss(
                model=resolved_loss_model,
                raw_outputs=raw_outputs,
                batch_targets=batch_targets,
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
                torch_module.nn.utils.clip_grad_norm_(
                    resolved_gradient_model.parameters(), grad_clip_norm
                )
            scaler.step(optimizer)
            scaler.update()
            if ema is not None:
                ema.update(resolved_ema_model)
            optimizer.zero_grad(set_to_none=True)
            last_optimizer_step_iteration = iteration

        for metric_name in epoch_losses:
            epoch_losses[metric_name] += float(loss_components[metric_name].detach().item())

        if batch_callback is not None and _is_yolov8_rank_zero(ddp_context):
            batch_callback(
                YoloV8DetectionTrainingBatchProgress(
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
                        "class_loss": float(loss_components["class_loss"].detach().item()),
                        "box_loss": float(loss_components["box_loss"].detach().item()),
                        "dfl_loss": float(loss_components["dfl_loss"].detach().item()),
                    },
                )
            )

    train_metrics = {
        metric_name: round(metric_total / max_iterations, 6)
        for metric_name, metric_total in epoch_losses.items()
    }
    train_metrics = _all_reduce_yolov8_detection_train_metrics(
        torch_module=torch_module,
        ddp_context=ddp_context,
        train_metrics=train_metrics,
    )
    return YoloV8DetectionTrainingEpochResult(
        global_iteration=global_iteration,
        train_metrics=train_metrics,
    )


def _resolve_yolov8_detection_epoch_samples(
    *,
    torch_module: Any,
    samples: tuple[Any, ...],
    epoch: int,
    ddp_context: DdpTrainingContext | None,
) -> list[Any]:
    """按当前 rank 解析一个 epoch 应读取的训练样本。"""

    if ddp_context is None:
        shuffled_samples = list(samples)
        random.shuffle(shuffled_samples)
        return shuffled_samples
    sampler = torch_module.utils.data.distributed.DistributedSampler(
        list(range(len(samples))),
        num_replicas=ddp_context.world_size,
        rank=ddp_context.rank,
        shuffle=True,
        seed=0,
        drop_last=False,
    )
    sampler.set_epoch(max(0, int(epoch) - 1))
    return [samples[index] for index in sampler]


def _all_reduce_yolov8_detection_train_metrics(
    *,
    torch_module: Any,
    ddp_context: DdpTrainingContext | None,
    train_metrics: dict[str, float],
) -> dict[str, float]:
    """把各 rank 的训练指标求平均，保证 rank0 看到全局训练摘要。"""

    if ddp_context is None or not ddp_context.is_distributed:
        return train_metrics
    distributed = torch_module.distributed
    if not distributed.is_available() or not distributed.is_initialized():
        return train_metrics
    metric_names = tuple(train_metrics.keys())
    reduce_device = (
        ddp_context.device
        if ddp_context.backend == "nccl" and ddp_context.device.startswith("cuda")
        else "cpu"
    )
    values = torch_module.tensor(
        [float(train_metrics[name]) for name in metric_names],
        dtype=torch_module.float64,
        device=reduce_device,
    )
    distributed.all_reduce(values, op=distributed.ReduceOp.SUM)
    values = values / max(1, int(ddp_context.world_size))
    return {
        metric_name: round(float(values[index].item()), 6)
        for index, metric_name in enumerate(metric_names)
    }


def _is_yolov8_rank_zero(ddp_context: DdpTrainingContext | None) -> bool:
    """判断当前 YOLOv8 detection 训练进程是否允许上报平台进度。"""

    return ddp_context is None or ddp_context.is_rank_zero


def _iter_yolov8_detection_batches(
    samples: list[Any],
    batch_size: int,
) -> list[list[Any]]:
    """把样本列表切成 YOLOv8 detection 训练 batch。"""

    resolved_batch_size = max(1, int(batch_size))
    return [
        samples[start:start + resolved_batch_size]
        for start in range(0, len(samples), resolved_batch_size)
    ]


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
