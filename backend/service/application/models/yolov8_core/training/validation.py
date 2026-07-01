"""YOLOv8 detection 验证损失执行入口。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)
from backend.service.application.models.yolov8_core.training.pytorch_dataloader import (
    YoloV8DetectionDataLoaderBatch,
)


def evaluate_yolov8_detection_validation_losses(
    *,
    torch_module: Any,
    model: Any,
    samples: tuple[Any, ...],
    batch_size: int,
    build_batch: Callable[[list[Any]], tuple[Any, tuple[Any, ...]]],
    unwrap_outputs: Callable[[Any], dict[str, Any]],
    compute_loss: Callable[..., dict[str, Any]],
    autocast_context: Callable[[], Any],
    freeze_batch_norm: Callable[[], tuple[object, ...]],
    restore_batch_norm: Callable[[tuple[object, ...]], None],
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    dataloader_batches: Iterable[YoloV8DetectionDataLoaderBatch] | None = None,
    device: str | None = None,
    runtime_precision: str = "fp32",
) -> dict[str, float]:
    """在验证集上统计 YOLOv8 detection loss。"""

    if not samples:
        return _empty_yolov8_detection_validation_losses()

    previous_training_mode = bool(model.training)
    model.train()
    batch_norm_states = freeze_batch_norm()
    epoch_totals = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
    batch_count = 0
    try:
        with torch_module.no_grad():
            if dataloader_batches is None:
                batch_iterator: Iterable[Any] = _iter_yolov8_validation_batches(
                    samples,
                    batch_size,
                )
            else:
                batch_iterator = dataloader_batches
            for batch_samples in batch_iterator:
                if isinstance(batch_samples, YoloV8DetectionDataLoaderBatch):
                    images = move_yolo_tensor_to_training_device(
                        batch_samples.images,
                        device=device or "cpu",
                        runtime_precision=runtime_precision,
                    )
                    batch_targets = batch_samples.targets
                else:
                    images, batch_targets = build_batch(batch_samples)
                with autocast_context():
                    raw_outputs = unwrap_outputs(model(images))
                    loss_components = compute_loss(
                        model=model,
                        raw_outputs=raw_outputs,
                        batch_targets=batch_targets,
                        class_loss_weight=class_loss_weight,
                        box_loss_weight=box_loss_weight,
                        dfl_loss_weight=dfl_loss_weight,
                        assign_topk=assign_topk,
                        assign_alpha=assign_alpha,
                        assign_beta=assign_beta,
                    )
                batch_count += 1
                for metric_name in epoch_totals:
                    epoch_totals[metric_name] += float(loss_components[metric_name].detach().item())
    finally:
        restore_batch_norm(batch_norm_states)
        model.train(previous_training_mode)

    if batch_count <= 0:
        return _empty_yolov8_detection_validation_losses()
    return {
        metric_name: round(metric_total / batch_count, 6)
        for metric_name, metric_total in epoch_totals.items()
    }


def _iter_yolov8_validation_batches(
    samples: tuple[Any, ...],
    batch_size: int,
) -> Iterable[list[Any]]:
    """按 batch size 迭代 YOLOv8 validation 样本。"""

    resolved_batch_size = max(1, int(batch_size))
    sample_list = list(samples)
    for start in range(0, len(sample_list), resolved_batch_size):
        yield sample_list[start:start + resolved_batch_size]


def _empty_yolov8_detection_validation_losses() -> dict[str, float]:
    """返回空验证集的 YOLOv8 detection loss 摘要。"""

    return {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}


__all__ = ["evaluate_yolov8_detection_validation_losses"]
