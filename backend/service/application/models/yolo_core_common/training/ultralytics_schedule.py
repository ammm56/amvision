"""普通 YOLO 训练调度规则。

本模块只放跨 YOLOv8 / YOLO11 / YOLO26 共用的 optimizer、warmup、
weight decay 缩放和 nominal batch size 规则。模型结构、loss、target 和
数据增强仍由各自 core 维护。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


YOLO_ULTRALYTICS_DEFAULT_NOMINAL_BATCH_SIZE = 64
YOLO_ULTRALYTICS_DEFAULT_LR0 = 0.01
YOLO_ULTRALYTICS_DEFAULT_LRF = 0.01
YOLO_ULTRALYTICS_DEFAULT_MOMENTUM = 0.937
YOLO_ULTRALYTICS_DEFAULT_WEIGHT_DECAY = 5e-4
YOLO_ULTRALYTICS_DEFAULT_WARMUP_EPOCHS = 3.0
YOLO_ULTRALYTICS_DEFAULT_WARMUP_MOMENTUM = 0.8
YOLO_ULTRALYTICS_DEFAULT_WARMUP_BIAS_LR = 0.1


@dataclass(frozen=True)
class YoloUltralyticsTrainingSchedule:
    """描述普通 YOLO 训练调度需要的公共状态。"""

    optimizer_name: str
    initial_lr: float
    momentum: float
    weight_decay: float
    scaled_weight_decay: float
    nominal_batch_size: int
    accumulate: int
    warmup_iterations: int
    warmup_momentum: float
    warmup_bias_lr: float
    final_lr_ratio: float
    max_epochs: int


def resolve_yolo_ultralytics_accumulate(
    *, batch_size: int, nominal_batch_size: int
) -> int:
    """按 Ultralytics 的 nominal batch size 规则计算梯度累积步数。"""

    resolved_batch_size = max(1, int(batch_size))
    resolved_nominal_batch_size = max(1, int(nominal_batch_size))
    return max(round(resolved_nominal_batch_size / resolved_batch_size), 1)


def build_yolo_ultralytics_optimizer(
    *,
    torch_module: Any,
    model: Any,
    num_classes: int,
    batch_size: int,
    train_sample_count: int,
    max_epochs: int,
    optimizer_name: str = "auto",
    learning_rate: float = YOLO_ULTRALYTICS_DEFAULT_LR0,
    momentum: float = YOLO_ULTRALYTICS_DEFAULT_MOMENTUM,
    weight_decay: float = YOLO_ULTRALYTICS_DEFAULT_WEIGHT_DECAY,
    nominal_batch_size: int = YOLO_ULTRALYTICS_DEFAULT_NOMINAL_BATCH_SIZE,
    final_lr_ratio: float = YOLO_ULTRALYTICS_DEFAULT_LRF,
    warmup_epochs: float = YOLO_ULTRALYTICS_DEFAULT_WARMUP_EPOCHS,
    warmup_momentum: float = YOLO_ULTRALYTICS_DEFAULT_WARMUP_MOMENTUM,
    warmup_bias_lr: float = YOLO_ULTRALYTICS_DEFAULT_WARMUP_BIAS_LR,
) -> tuple[Any, YoloUltralyticsTrainingSchedule]:
    """构建对齐 Ultralytics 训练策略的 optimizer 和调度摘要。"""

    resolved_batch_size = max(1, int(batch_size))
    resolved_max_epochs = max(1, int(max_epochs))
    resolved_nominal_batch_size = max(1, int(nominal_batch_size))
    accumulate = resolve_yolo_ultralytics_accumulate(
        batch_size=resolved_batch_size,
        nominal_batch_size=resolved_nominal_batch_size,
    )
    scaled_weight_decay = (
        float(weight_decay)
        * float(resolved_batch_size)
        * float(accumulate)
        / float(resolved_nominal_batch_size)
    )
    iterations = (
        math.ceil(
            max(1, int(train_sample_count))
            / float(max(resolved_batch_size, resolved_nominal_batch_size))
        )
        * resolved_max_epochs
    )
    resolved_optimizer_name, resolved_lr, resolved_momentum, resolved_warmup_bias_lr = (
        _resolve_yolo_optimizer_auto(
            optimizer_name=optimizer_name,
            num_classes=num_classes,
            iterations=iterations,
            learning_rate=learning_rate,
            momentum=momentum,
            warmup_bias_lr=warmup_bias_lr,
        )
    )
    param_groups = _build_yolo_optimizer_param_groups(
        torch_module=torch_module,
        model=model,
        optimizer_name=resolved_optimizer_name,
        learning_rate=resolved_lr,
        momentum=resolved_momentum,
        weight_decay=scaled_weight_decay,
    )
    optimizer = _create_yolo_optimizer(
        torch_module=torch_module,
        optimizer_name=resolved_optimizer_name,
        param_groups=param_groups,
    )
    batches_per_epoch = max(
        1,
        math.ceil(max(1, int(train_sample_count)) / float(resolved_batch_size)),
    )
    warmup_iterations = (
        max(round(float(warmup_epochs) * batches_per_epoch), 100)
        if float(warmup_epochs) > 0
        else -1
    )
    schedule = YoloUltralyticsTrainingSchedule(
        optimizer_name=resolved_optimizer_name,
        initial_lr=float(resolved_lr),
        momentum=float(resolved_momentum),
        weight_decay=float(weight_decay),
        scaled_weight_decay=float(scaled_weight_decay),
        nominal_batch_size=resolved_nominal_batch_size,
        accumulate=accumulate,
        warmup_iterations=int(warmup_iterations),
        warmup_momentum=float(warmup_momentum),
        warmup_bias_lr=float(resolved_warmup_bias_lr),
        final_lr_ratio=float(final_lr_ratio),
        max_epochs=resolved_max_epochs,
    )
    return optimizer, schedule


def build_yolo_ultralytics_scheduler(
    *, torch_module: Any, optimizer: Any, max_epochs: int, final_lr_ratio: float
) -> Any:
    """构建 Ultralytics 默认的 cosine LambdaLR scheduler。"""

    return torch_module.optim.lr_scheduler.LambdaLR(
        optimizer,
        lr_lambda=lambda epoch: compute_yolo_ultralytics_lr_factor(
            epoch=epoch,
            max_epochs=max_epochs,
            final_lr_ratio=final_lr_ratio,
        ),
    )


def compute_yolo_ultralytics_lr_factor(
    *, epoch: int, max_epochs: int, final_lr_ratio: float
) -> float:
    """计算 Ultralytics one-cycle cosine 学习率倍率。"""

    resolved_max_epochs = max(1, int(max_epochs))
    progress = max(0.0, min(float(epoch), float(resolved_max_epochs)))
    return (
        max((1.0 - math.cos(progress * math.pi / float(resolved_max_epochs))) / 2.0, 0.0)
        * (float(final_lr_ratio) - 1.0)
        + 1.0
    )


def apply_yolo_ultralytics_warmup(
    *,
    optimizer: Any,
    schedule: YoloUltralyticsTrainingSchedule,
    iteration_index: int,
    epoch: int,
    batch_size: int,
) -> int:
    """按 Ultralytics warmup 规则更新当前 batch 的 lr、momentum 和累积步数。"""

    if schedule.warmup_iterations < 0 or int(iteration_index) > schedule.warmup_iterations:
        return int(schedule.accumulate)
    current_position = max(0.0, float(iteration_index))
    warmup_iterations = max(1.0, float(schedule.warmup_iterations))
    target_accumulate = max(
        1.0, float(schedule.nominal_batch_size) / float(max(1, int(batch_size)))
    )
    accumulate = max(
        1,
        int(round(_linear_interpolate(current_position, 0.0, warmup_iterations, 1.0, target_accumulate))),
    )
    epoch_lr_factor = compute_yolo_ultralytics_lr_factor(
        epoch=max(0, int(epoch) - 1),
        max_epochs=schedule.max_epochs,
        final_lr_ratio=schedule.final_lr_ratio,
    )
    for param_group in optimizer.param_groups:
        initial_lr = float(param_group.get("initial_lr", schedule.initial_lr))
        start_lr = schedule.warmup_bias_lr if param_group.get("param_group") == "bias" else 0.0
        param_group["lr"] = _linear_interpolate(
            current_position,
            0.0,
            warmup_iterations,
            start_lr,
            initial_lr * epoch_lr_factor,
        )
        if "momentum" in param_group:
            param_group["momentum"] = _linear_interpolate(
                current_position,
                0.0,
                warmup_iterations,
                schedule.warmup_momentum,
                schedule.momentum,
            )
    return accumulate


def _resolve_yolo_optimizer_auto(
    *,
    optimizer_name: str,
    num_classes: int,
    iterations: int,
    learning_rate: float,
    momentum: float,
    warmup_bias_lr: float,
) -> tuple[str, float, float, float]:
    """解析 Ultralytics `optimizer=auto` 对应的 optimizer、lr 和 momentum。"""

    requested_name = str(optimizer_name or "auto").strip().lower()
    if requested_name == "auto":
        lr_fit = round(0.002 * 5.0 / float(4 + max(1, int(num_classes))), 6)
        if int(iterations) > 10000:
            return "SGD", 0.01, 0.9, warmup_bias_lr
        return "AdamW", lr_fit, 0.9, 0.0
    supported_names = {
        "adam": "Adam",
        "adamw": "AdamW",
        "nadam": "NAdam",
        "radam": "RAdam",
        "rmsprop": "RMSProp",
        "sgd": "SGD",
    }
    resolved_name = supported_names.get(requested_name)
    if resolved_name is None:
        raise ValueError(f"不支持的 YOLO optimizer: {optimizer_name}")
    return resolved_name, float(learning_rate), float(momentum), float(warmup_bias_lr)


def _build_yolo_optimizer_param_groups(
    *,
    torch_module: Any,
    model: Any,
    optimizer_name: str,
    learning_rate: float,
    momentum: float,
    weight_decay: float,
) -> list[dict[str, object]]:
    """按 Ultralytics 参数分组规则拆分 decay、norm 和 bias 参数。"""

    norm_types = tuple(
        value for key, value in torch_module.nn.__dict__.items() if "Norm" in key
    )
    decay_params: list[Any] = []
    norm_params: list[Any] = []
    bias_params: list[Any] = []
    for module_name, module in model.named_modules():
        for param_name, parameter in module.named_parameters(recurse=False):
            if not getattr(parameter, "requires_grad", False):
                continue
            full_name = f"{module_name}.{param_name}" if module_name else param_name
            if "bias" in full_name:
                bias_params.append(parameter)
            elif isinstance(module, norm_types) or "logit_scale" in full_name:
                norm_params.append(parameter)
            else:
                decay_params.append(parameter)
    base_options = _build_yolo_optimizer_group_options(
        optimizer_name=optimizer_name,
        learning_rate=learning_rate,
        momentum=momentum,
    )
    return [
        {
            "params": decay_params,
            **base_options,
            "weight_decay": float(weight_decay),
            "param_group": "weight",
            "initial_lr": float(learning_rate),
        },
        {
            "params": norm_params,
            **base_options,
            "weight_decay": 0.0,
            "param_group": "bn",
            "initial_lr": float(learning_rate),
        },
        {
            "params": bias_params,
            **base_options,
            "weight_decay": 0.0,
            "param_group": "bias",
            "initial_lr": float(learning_rate),
        },
    ]


def _build_yolo_optimizer_group_options(
    *, optimizer_name: str, learning_rate: float, momentum: float
) -> dict[str, object]:
    """构造不同 optimizer 对应的参数组基础选项。"""

    if optimizer_name in {"Adam", "AdamW", "NAdam", "RAdam"}:
        return {"lr": float(learning_rate), "betas": (float(momentum), 0.999)}
    if optimizer_name == "RMSProp":
        return {"lr": float(learning_rate), "momentum": float(momentum)}
    if optimizer_name == "SGD":
        return {
            "lr": float(learning_rate),
            "momentum": float(momentum),
            "nesterov": True,
        }
    raise ValueError(f"不支持的 YOLO optimizer: {optimizer_name}")


def _create_yolo_optimizer(
    *, torch_module: Any, optimizer_name: str, param_groups: list[dict[str, object]]
) -> Any:
    """创建 torch optimizer 实例。"""

    optimizer_cls = getattr(torch_module.optim, optimizer_name, None)
    if optimizer_cls is None:
        raise ValueError(f"当前 torch 环境不支持 optimizer: {optimizer_name}")
    return optimizer_cls(param_groups)


def _linear_interpolate(
    position: float,
    start_x: float,
    end_x: float,
    start_y: float,
    end_y: float,
) -> float:
    """执行一维线性插值。"""

    if end_x <= start_x:
        return float(end_y)
    ratio = max(0.0, min(1.0, (float(position) - start_x) / (end_x - start_x)))
    return float(start_y) + ratio * (float(end_y) - float(start_y))


__all__ = [
    "YOLO_ULTRALYTICS_DEFAULT_LR0",
    "YOLO_ULTRALYTICS_DEFAULT_LRF",
    "YOLO_ULTRALYTICS_DEFAULT_MOMENTUM",
    "YOLO_ULTRALYTICS_DEFAULT_NOMINAL_BATCH_SIZE",
    "YOLO_ULTRALYTICS_DEFAULT_WARMUP_BIAS_LR",
    "YOLO_ULTRALYTICS_DEFAULT_WARMUP_EPOCHS",
    "YOLO_ULTRALYTICS_DEFAULT_WARMUP_MOMENTUM",
    "YOLO_ULTRALYTICS_DEFAULT_WEIGHT_DECAY",
    "YoloUltralyticsTrainingSchedule",
    "apply_yolo_ultralytics_warmup",
    "build_yolo_ultralytics_optimizer",
    "build_yolo_ultralytics_scheduler",
    "compute_yolo_ultralytics_lr_factor",
    "resolve_yolo_ultralytics_accumulate",
]
