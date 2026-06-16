"""YOLOX validation loss 评估工具。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def evaluate_yolox_validation_losses(
    *,
    torch_module: Any,
    autocast_context_factory: Callable[..., Any],
    model: Any,
    loader: Any,
    device: str,
    precision: str,
) -> dict[str, float]:
    """在不更新参数的前提下执行一次 YOLOX validation loss 统计。"""

    if len(loader) == 0:
        return {}

    was_training = bool(model.training)
    model.train()
    batch_norm_states = _freeze_batch_norm_modules(torch_module=torch_module, model=model)
    try:
        with torch_module.no_grad():
            epoch_totals: dict[str, float] = {}
            epoch_iterations = 0
            for images, targets, _image_infos, _image_ids in loader:
                images = images.to(device=device, dtype=torch_module.float32)
                targets = targets.to(device=device, dtype=torch_module.float32)
                with autocast_context_factory(
                    torch_module=torch_module,
                    device=device,
                    precision=precision,
                ):
                    outputs = model(images, targets)
                scalar_outputs = _convert_yolox_loss_outputs(outputs)
                for metric_name, metric_value in scalar_outputs.items():
                    epoch_totals[metric_name] = epoch_totals.get(metric_name, 0.0) + metric_value
                epoch_iterations += 1
    finally:
        _restore_batch_norm_modules(batch_norm_states)
        model.train(was_training)

    return {
        metric_name: metric_total / epoch_iterations
        for metric_name, metric_total in epoch_totals.items()
    }


def _convert_yolox_loss_outputs(outputs: dict[str, object]) -> dict[str, float]:
    """把 YOLOX loss forward 输出转换为可序列化标量。"""

    scalar_outputs: dict[str, float] = {}
    for key, value in outputs.items():
        if hasattr(value, "detach"):
            scalar_outputs[key] = float(value.detach().cpu().item())
        elif isinstance(value, int | float):
            scalar_outputs[key] = float(value)
    return scalar_outputs


def _freeze_batch_norm_modules(
    *,
    torch_module: Any,
    model: Any,
) -> tuple[tuple[Any, bool], ...]:
    """在 validation loss 阶段临时冻结 BatchNorm 统计更新。"""

    batch_norm_states: list[tuple[Any, bool]] = []
    for module in model.modules():
        if isinstance(module, torch_module.nn.BatchNorm2d):
            batch_norm_states.append((module, bool(module.training)))
            module.eval()
    return tuple(batch_norm_states)


def _restore_batch_norm_modules(batch_norm_states: tuple[tuple[Any, bool], ...]) -> None:
    """恢复 validation 前 BatchNorm 的训练状态。"""

    for module, was_training in batch_norm_states:
        module.train(was_training)
