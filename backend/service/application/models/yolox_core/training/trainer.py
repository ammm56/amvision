"""YOLOX detection 训练器公共定义。"""

from __future__ import annotations

import io
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolox_core.cfg import YOLOX_DEFAULT_INPUT_SIZE
from backend.service.application.models.yolox_core.utils.torch_runtime import (
    build_yolox_autocast_context,
)


@dataclass(frozen=True)
class YoloXTrainingEpochProgress:
    """描述单轮训练结束后的进度快照。

    字段：
    - epoch：当前完成的 epoch 序号。
    - max_epochs：本次训练总 epoch 数。
    - evaluation_interval：真实验证评估周期。
    - validation_ran：当前轮是否执行了真实验证评估。
    - evaluated_epochs：截至当前轮已执行真实验证评估的 epoch 列表。
    - train_metrics：当前轮训练指标摘要。
    - validation_metrics：当前轮验证指标摘要。
    - train_metrics_snapshot：当前轮结束后形成的完整训练指标快照。
    - validation_snapshot：当前轮评估完成后形成的完整验证快照；未执行评估时为空。
    - current_metric_name：当前用于比较的指标名。
    - current_metric_value：当前轮该指标值；当前轮未执行评估时为空。
    - best_metric_name：当前最佳指标名。
    - best_metric_value：截至当前轮的最佳指标值；首次评估前为空。
    """

    epoch: int
    max_epochs: int
    evaluation_interval: int
    validation_ran: bool
    evaluated_epochs: tuple[int, ...]
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_snapshot: dict[str, object] | None
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float | None


@dataclass(frozen=True)
class YoloXTrainingBatchProgress:
    """描述单个训练 batch 完成后的 heartbeat 快照。

    字段：
    - epoch：当前 epoch 序号。
    - max_epochs：训练总 epoch 数。
    - iteration：当前 epoch 内已完成的 batch 序号。
    - max_iterations：当前 epoch 总 batch 数。
    - global_iteration：全局已完成的 batch 数。
    - total_iterations：整个训练任务的总 batch 数。
    - input_size：当前 batch 使用的输入尺寸。
    - learning_rate：当前 batch 更新后的学习率。
    - train_metrics：当前 batch 的训练指标摘要。
    """

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
class YoloXTrainingControlCommand:
    """描述单轮训练结束后由上层返回给训练循环的控制命令。

    字段：
    - save_checkpoint：是否在当前 epoch 边界生成并交付 savepoint。
    - pause_training：是否在交付 savepoint 后暂停训练。
    - terminate_training：是否在当前 epoch 边界终止训练。
    """

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class YoloXTrainingSavePoint:
    """描述训练在某个 epoch 边界导出的可恢复 savepoint。

    字段：
    - epoch：当前 savepoint 对应的已完成 epoch。
    - latest_checkpoint_bytes：用于继续训练的 latest checkpoint 二进制内容。
    - best_checkpoint_bytes：当前 best checkpoint 二进制内容；在尚未产生 best checkpoint 时为空。
    - best_metric_name：当前最佳指标名称。
    - best_metric_value：当前最佳指标值；尚未产生时为空。
    """

    epoch: int
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None = None
    best_metric_name: str = ""
    best_metric_value: float | None = None


@dataclass(frozen=True)
class LoadedYoloXResumeState:
    """描述从 latest checkpoint 解析出的恢复训练状态。

    字段：
    - resume_epoch：恢复前已经完成的 epoch 数。
    - epoch_history：恢复前累计的训练指标轨迹。
    - validation_history：恢复前累计的验证指标轨迹。
    - best_metric_name：恢复前记录的最佳指标名称。
    - best_metric_value：恢复前记录的最佳指标值。
    - best_checkpoint_state：恢复前缓存的 best checkpoint 状态；为空时表示尚未产生。
    - warm_start_summary：恢复后继续沿用的 warm start 摘要。
    """

    resume_epoch: int
    epoch_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    best_metric_name: str
    best_metric_value: float | None
    best_checkpoint_state: dict[str, object] | None
    warm_start_summary: dict[str, object]


@dataclass(frozen=True)
class YoloXTrainingLoopRequest:
    """描述 YOLOX core 训练循环的完整输入。

    字段：
    - torch_module：当前训练使用的 torch 模块。
    - base_model：原始 YOLOX 模型。
    - training_model：实际执行 forward/backward 的模型。
    - train_dataset：训练数据集，可能是 MosaicDetection 包装后的数据集。
    - train_loader：训练 DataLoader。
    - validation_loader：验证 DataLoader；为空时只做训练损失链。
    - optimizer：训练 optimizer。
    - scheduler：YOLOX LR scheduler。
    - grad_scaler：AMP GradScaler。
    - model_ema：可选 ModelEMA。
    - validation_evaluator：验证回调，输入当前评估模型，返回验证指标。
    - batch_callback：batch heartbeat 回调。
    - epoch_callback：epoch 结束控制回调。
    - savepoint_callback：save/pause savepoint 回调。
    """

    torch_module: Any
    base_model: Any
    training_model: Any
    train_dataset: Any
    train_loader: Any
    validation_loader: Any | None
    optimizer: Any
    scheduler: Any
    grad_scaler: Any
    model_ema: Any | None
    validation_evaluator: Callable[[Any], dict[str, float]] | None
    batch_callback: Callable[[YoloXTrainingBatchProgress], None] | None
    epoch_callback: Callable[
        [YoloXTrainingEpochProgress],
        YoloXTrainingControlCommand | None,
    ] | None
    savepoint_callback: Callable[[YoloXTrainingSavePoint], None] | None
    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str
    precision: str
    input_size: tuple[int, int]
    current_input_size: tuple[int, int]
    batch_size: int
    max_epochs: int
    evaluation_interval: int
    train_split_name: str
    validation_split_name: str | None
    validation_sample_count: int
    total_sample_count: int
    train_sample_count: int
    train_category_names: tuple[str, ...]
    model_scale: str
    parameter_count: int
    warm_start_summary: dict[str, object]
    start_epoch: int = 0
    epoch_history: list[dict[str, object]] | None = None
    validation_epoch_history: list[dict[str, object]] | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    best_checkpoint_state: dict[str, object] | None = None
    no_aug_epochs: int = 0
    multiscale_range: int = 0
    random_seed: int = 0
    evaluation_confidence_threshold: float | None = None
    evaluation_nms_threshold: float | None = None


@dataclass(frozen=True)
class YoloXTrainingLoopResult:
    """描述 YOLOX core 训练循环的执行结果。

    字段：
    - status：执行状态，取值为 completed、paused 或 terminated。
    - savepoint：暂停前生成的 savepoint；非 paused 时为空。
    - checkpoint_bytes：best checkpoint 二进制；completed 时必填。
    - latest_checkpoint_bytes：latest checkpoint 二进制；completed 时必填。
    - metrics_payload：train-metrics.json 载荷；completed 时必填。
    - validation_metrics_payload：validation-metrics.json 载荷；completed 时必填。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - final_metrics：最后一轮训练指标。
    """

    status: str
    savepoint: YoloXTrainingSavePoint | None = None
    checkpoint_bytes: bytes | None = None
    latest_checkpoint_bytes: bytes | None = None
    metrics_payload: dict[str, object] | None = None
    validation_metrics_payload: dict[str, object] | None = None
    best_metric_name: str = ""
    best_metric_value: float | None = None
    final_metrics: dict[str, object] | None = None


# 训练结果与接口文档会公开这一实现模式标识，用于区分当前 YOLOX detection 训练链路。
YOLOX_DETECTION_CORE_IMPLEMENTATION_MODE = "yolox-detection-core"
# 未显式指定 input_size 时，固定使用 640x640 作为训练默认尺寸。
YOLOX_CORE_DEFAULT_INPUT_SIZE = YOLOX_DEFAULT_INPUT_SIZE
# 未显式指定 batch_size 时，默认按单 batch 执行。
YOLOX_CORE_DEFAULT_BATCH_SIZE = 1
# 未显式指定 max_epochs 时，默认只跑 1 个 epoch。
YOLOX_CORE_DEFAULT_MAX_EPOCHS = 1
# 未显式指定 evaluation_interval 时，默认每 5 个 epoch 做一次真实验证评估。
YOLOX_CORE_DEFAULT_EVALUATION_INTERVAL = 5
# 验证阶段 COCO mAP 评估默认使用的 confidence threshold。
YOLOX_CORE_DEFAULT_EVAL_CONFIDENCE_THRESHOLD = 0.01
# 验证阶段 COCO mAP 评估默认使用的 NMS threshold。
YOLOX_CORE_DEFAULT_EVAL_NMS_THRESHOLD = 0.65

# 默认训练增强按 YOLOX reference 配置执行，特殊场景可通过 extra_options 显式关闭。
YOLOX_DEFAULT_TRAIN_FLIP_PROB = 0.5
YOLOX_DEFAULT_TRAIN_HSV_PROB = 1.0
YOLOX_DEFAULT_TRAIN_MOSAIC_PROB = 1.0
YOLOX_DEFAULT_TRAIN_MIXUP_PROB = 1.0
YOLOX_DEFAULT_TRAIN_ENABLE_MIXUP = True
YOLOX_DEFAULT_TRAIN_MULTISCALE_RANGE = 5

# 以下值用于训练调度、摘要和测试中的 reference 对齐检查。
YOLOX_REFERENCE_DEFAULT_FLIP_PROB = 0.5
YOLOX_REFERENCE_DEFAULT_HSV_PROB = 1.0
YOLOX_REFERENCE_DEFAULT_MAX_LABELS = 120
YOLOX_REFERENCE_DEFAULT_WARMUP_EPOCHS = 5
YOLOX_REFERENCE_DEFAULT_NO_AUG_EPOCHS = 15
YOLOX_REFERENCE_DEFAULT_MIN_LR_RATIO = 0.05
YOLOX_REFERENCE_DEFAULT_MOSAIC_PROB = 1.0
YOLOX_REFERENCE_DEFAULT_MIXUP_PROB = 1.0
YOLOX_REFERENCE_DEFAULT_DEGREES = 10.0
YOLOX_REFERENCE_DEFAULT_TRANSLATE = 0.1
YOLOX_REFERENCE_DEFAULT_MOSAIC_SCALE = (0.1, 2.0)
YOLOX_REFERENCE_DEFAULT_MIXUP_SCALE = (0.5, 1.5)
YOLOX_REFERENCE_DEFAULT_SHEAR = 2.0
YOLOX_REFERENCE_DEFAULT_ENABLE_MIXUP = True
YOLOX_REFERENCE_DEFAULT_MULTISCALE_RANGE = 5
YOLOX_REFERENCE_DEFAULT_EMA_ENABLED = True
# ModelEMA 当前固定使用 reference 对齐的 decay 值，不开放成独立公开参数。
YOLOX_REFERENCE_DEFAULT_EMA_DECAY = 0.9998


def resolve_yolox_training_schedule_options(
    *,
    extra_options: dict[str, object],
    max_epochs: int,
) -> tuple[int, int, float]:
    """解析并约束 YOLOX warmup/no_aug 调度配置。"""

    warmup_epochs = max(
        0,
        _read_int_option(
            extra_options,
            "warmup_epochs",
            default=YOLOX_REFERENCE_DEFAULT_WARMUP_EPOCHS,
        ),
    )
    no_aug_epochs = max(
        0,
        _read_int_option(
            extra_options,
            "no_aug_epochs",
            default=YOLOX_REFERENCE_DEFAULT_NO_AUG_EPOCHS,
        ),
    )
    min_lr_ratio = min(
        1.0,
        max(
            0.0,
            _read_float_option(
                extra_options,
                "min_lr_ratio",
                default=YOLOX_REFERENCE_DEFAULT_MIN_LR_RATIO,
            ),
        ),
    )
    if max_epochs <= 1:
        return 0, 0, min_lr_ratio

    warmup_epochs = min(warmup_epochs, max_epochs - 1)
    max_no_aug_epochs = max(0, max_epochs - warmup_epochs - 1)
    no_aug_epochs = min(no_aug_epochs, max_no_aug_epochs)
    return warmup_epochs, no_aug_epochs, min_lr_ratio


def is_yolox_no_aug_epoch(*, epoch: int, max_epochs: int, no_aug_epochs: int) -> bool:
    """判断当前 epoch 是否位于 YOLOX no_aug 尾段。"""

    return no_aug_epochs > 0 and epoch > max_epochs - no_aug_epochs


def set_yolox_head_use_l1(*, model: Any, enabled: bool) -> None:
    """在 no_aug 阶段切换 YOLOXHead.use_l1。"""

    resolved_model = getattr(model, "module", model)
    head = getattr(resolved_model, "head", None)
    if head is None or not hasattr(head, "use_l1"):
        return
    head.use_l1 = bool(enabled)


def resolve_yolox_evaluation_model(*, training_model: Any, model_ema: Any | None) -> Any:
    """解析当前验证和导出 checkpoint 应使用的模型对象。"""

    if model_ema is not None:
        return model_ema.ema
    return training_model


def set_yolox_training_loader_input_size(
    *,
    train_dataset: Any,
    train_loader: Any,
    input_size: tuple[int, int],
) -> None:
    """同步更新 YOLOX 训练数据集和 batch sampler 的输入尺寸。"""

    if hasattr(train_dataset, "set_input_dim"):
        train_dataset.set_input_dim(tuple(input_size))
    batch_sampler = getattr(train_loader, "batch_sampler", None)
    if batch_sampler is not None and hasattr(batch_sampler, "set_input_dimension"):
        batch_sampler.set_input_dimension(tuple(input_size))


def set_yolox_training_loader_mosaic_enabled(
    *,
    train_dataset: Any,
    train_loader: Any,
    enabled: bool,
) -> None:
    """同步切换 YOLOX 训练数据集与 batch sampler 的 Mosaic 开关。"""

    if hasattr(train_dataset, "enable_mosaic"):
        train_dataset.enable_mosaic = bool(enabled)
    if not enabled and hasattr(train_dataset, "close_mosaic"):
        train_dataset.close_mosaic()
    batch_sampler = getattr(train_loader, "batch_sampler", None)
    if batch_sampler is not None and hasattr(batch_sampler, "mosaic"):
        batch_sampler.mosaic = bool(enabled)


def random_resize_yolox_input_size(
    *,
    base_input_size: tuple[int, int],
    multiscale_range: int,
    random_seed: int,
) -> tuple[int, int]:
    """按 YOLOX 多尺度规则为后续 batch 生成新的输入尺寸。"""

    if multiscale_range <= 0:
        return tuple(base_input_size)

    input_height, input_width = base_input_size
    size_factor = input_width * 1.0 / input_height
    rng = random.Random(random_seed)
    min_size = max(1, int(input_height / 32) - multiscale_range)
    max_size = max(min_size, int(input_height / 32) + multiscale_range)
    size = rng.randint(min_size, max_size)
    return 32 * size, 32 * int(size * size_factor)


def preprocess_yolox_training_batch(
    *,
    torch_module: Any,
    images: Any,
    targets: Any,
    target_size: tuple[int, int],
):
    """按当前多尺度目标尺寸对 YOLOX 训练 batch 张量做插值和标签缩放。"""

    current_height = int(images.shape[-2])
    current_width = int(images.shape[-1])
    scale_y = target_size[0] / current_height
    scale_x = target_size[1] / current_width
    if scale_x == 1.0 and scale_y == 1.0:
        return images, targets

    resized_images = torch_module.nn.functional.interpolate(
        images,
        size=target_size,
        mode="bilinear",
        align_corners=False,
    )
    resized_targets = targets.clone()
    resized_targets[..., 1::2] = resized_targets[..., 1::2] * scale_x
    resized_targets[..., 2::2] = resized_targets[..., 2::2] * scale_y
    return resized_images, resized_targets


def build_yolox_batch_progress_metrics(batch_metrics: dict[str, float]) -> dict[str, float]:
    """把当前 YOLOX batch 的标量输出转换为 heartbeat 可用的指标字典。"""

    return {
        key: float(value)
        for key, value in batch_metrics.items()
        if isinstance(value, int | float)
    }


def build_yolox_optimizer(*, torch_module: Any, model: Any, batch_size: int):
    """按 YOLOX 参数分组规则创建 SGD optimizer。"""

    learning_rate = (0.01 / 64.0) * batch_size
    pg0: list[object] = []
    pg1: list[object] = []
    pg2: list[object] = []
    for module_name, module in model.named_modules():
        if hasattr(module, "bias") and isinstance(module.bias, torch_module.nn.Parameter):
            pg2.append(module.bias)
        if isinstance(module, torch_module.nn.BatchNorm2d) or "bn" in module_name:
            pg0.append(module.weight)
        elif hasattr(module, "weight") and isinstance(module.weight, torch_module.nn.Parameter):
            pg1.append(module.weight)

    optimizer = torch_module.optim.SGD(pg0, lr=learning_rate, momentum=0.9, nesterov=True)
    optimizer.add_param_group({"params": pg1, "weight_decay": 5e-4})
    optimizer.add_param_group({"params": pg2})
    return optimizer


def build_yolox_lr_scheduler(
    *,
    scheduler_class: Any,
    train_loader_length: int,
    batch_size: int,
    max_epochs: int,
    warmup_epochs: int,
    no_aug_epochs: int,
    min_lr_ratio: float,
):
    """创建 YOLOX warm cosine LR scheduler。"""

    return scheduler_class(
        "yoloxwarmcos",
        (0.01 / 64.0) * batch_size,
        train_loader_length,
        max_epochs,
        warmup_epochs=warmup_epochs,
        warmup_lr_start=0,
        no_aug_epochs=no_aug_epochs,
        min_lr_ratio=min_lr_ratio,
    )


def build_yolox_model_ema(
    *,
    ema_class: Any,
    model: Any,
    enabled: bool,
) -> Any | None:
    """按配置创建 YOLOX ModelEMA。"""

    if not enabled:
        return None
    return ema_class(
        model,
        decay=YOLOX_REFERENCE_DEFAULT_EMA_DECAY,
        updates=0,
    )


def load_yolox_resume_checkpoint(
    *,
    torch_module: Any,
    model: Any,
    optimizer: Any,
    checkpoint_path: Path,
    expected_category_names: tuple[str, ...],
    expected_model_scale: str,
    expected_input_size: tuple[int, int],
    expected_precision: str,
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
) -> LoadedYoloXResumeState:
    """从 latest checkpoint 中恢复模型、optimizer 和训练历史。"""

    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "resume checkpoint 不存在",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        )

    try:
        checkpoint_payload = torch_module.load(str(checkpoint_path), map_location="cpu")
    except Exception as error:
        raise ServiceConfigurationError(
            "resume checkpoint 读取失败",
            details={"checkpoint_path": checkpoint_path.as_posix()},
        ) from error

    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError("resume checkpoint 内容不合法")

    model_state = checkpoint_payload.get("model")
    optimizer_state = checkpoint_payload.get("optimizer")
    if not isinstance(model_state, dict) or not isinstance(optimizer_state, dict):
        raise InvalidRequestError("resume checkpoint 缺少模型或优化器状态")

    checkpoint_category_names = checkpoint_payload.get("category_names")
    if isinstance(checkpoint_category_names, list):
        normalized_category_names = tuple(
            item
            for item in checkpoint_category_names
            if isinstance(item, str) and item.strip()
        )
        if normalized_category_names and normalized_category_names != expected_category_names:
            raise InvalidRequestError("resume checkpoint 的类别列表与当前任务不一致")

    checkpoint_model_scale = checkpoint_payload.get("model_scale")
    if isinstance(checkpoint_model_scale, str) and checkpoint_model_scale != expected_model_scale:
        raise InvalidRequestError("resume checkpoint 的 model_scale 与当前任务不一致")

    checkpoint_input_size = checkpoint_payload.get("input_size")
    if (
        isinstance(checkpoint_input_size, list)
        and len(checkpoint_input_size) == 2
        and all(isinstance(item, int) for item in checkpoint_input_size)
        and tuple(checkpoint_input_size) != expected_input_size
    ):
        raise InvalidRequestError("resume checkpoint 的 input_size 与当前任务不一致")

    checkpoint_precision = checkpoint_payload.get("precision")
    if isinstance(checkpoint_precision, str) and checkpoint_precision != expected_precision:
        raise InvalidRequestError("resume checkpoint 的 precision 与当前任务不一致")

    _validate_resume_validation_configuration(
        checkpoint_payload=checkpoint_payload,
        expected_validation_split_name=expected_validation_split_name,
        expected_evaluation_interval=expected_evaluation_interval,
        expected_evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
        expected_evaluation_nms_threshold=expected_evaluation_nms_threshold,
    )

    model.load_state_dict({str(key): value for key, value in model_state.items()}, strict=True)
    optimizer.load_state_dict(optimizer_state)
    move_yolox_optimizer_state_to_device(
        optimizer=optimizer,
        device=str(next(model.parameters()).device),
    )

    resume_epoch = checkpoint_payload.get("epoch")
    if not isinstance(resume_epoch, int) or resume_epoch < 0:
        raise InvalidRequestError("resume checkpoint 缺少有效的 epoch")

    epoch_history = normalize_yolox_history_items(checkpoint_payload.get("epoch_history"))
    validation_history = normalize_yolox_history_items(checkpoint_payload.get("validation_history"))
    best_metric_name = checkpoint_payload.get("best_metric_name")
    if not isinstance(best_metric_name, str) or not best_metric_name.strip():
        metric_name = checkpoint_payload.get("metric_name")
        if isinstance(metric_name, str) and metric_name.strip():
            best_metric_name = metric_name
        else:
            best_metric_name = ""

    raw_best_metric_value = checkpoint_payload.get("best_metric_value")
    if isinstance(raw_best_metric_value, int | float):
        best_metric_value: float | None = float(raw_best_metric_value)
    else:
        raw_metric_value = checkpoint_payload.get("metric_value")
        if isinstance(raw_metric_value, int | float):
            best_metric_value = float(raw_metric_value)
        else:
            best_metric_value = None

    raw_best_checkpoint_state = checkpoint_payload.get("best_checkpoint_state")
    best_checkpoint_state = (
        {str(key): value for key, value in raw_best_checkpoint_state.items()}
        if isinstance(raw_best_checkpoint_state, dict)
        else None
    )
    warm_start_summary = checkpoint_payload.get("warm_start_summary")
    return LoadedYoloXResumeState(
        resume_epoch=resume_epoch,
        epoch_history=epoch_history,
        validation_history=validation_history,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=best_checkpoint_state,
        warm_start_summary=(
            dict(warm_start_summary)
            if isinstance(warm_start_summary, dict)
            else {"enabled": False}
        ),
    )


def normalize_yolox_history_items(history_payload: object) -> list[dict[str, object]]:
    """把 checkpoint 中的历史轨迹载荷规范化为字典列表。"""

    if not isinstance(history_payload, list):
        return []

    normalized_history: list[dict[str, object]] = []
    for item in history_payload:
        if isinstance(item, dict):
            normalized_history.append({str(key): value for key, value in item.items()})
    return normalized_history


def move_yolox_optimizer_state_to_device(*, optimizer: Any, device: str) -> None:
    """把恢复后的 optimizer state 张量迁移到当前训练 device。"""

    for state in optimizer.state.values():
        if not isinstance(state, dict):
            continue
        for key, value in list(state.items()):
            if hasattr(value, "to"):
                state[key] = value.to(device=device)


def serialize_yolox_checkpoint_bytes(
    *,
    torch_module: Any,
    checkpoint_state: dict[str, object],
) -> bytes:
    """把 YOLOX checkpoint 状态序列化为二进制内容。"""

    checkpoint_buffer = io.BytesIO()
    torch_module.save(checkpoint_state, checkpoint_buffer)
    return checkpoint_buffer.getvalue()


def build_yolox_checkpoint_state(
    *,
    model: Any,
    optimizer: Any,
    epoch: int,
    metric_name: str,
    metric_value: float,
    category_names: tuple[str, ...],
    model_scale: str,
    input_size: tuple[int, int],
    precision: str,
    gpu_count: int,
    device_ids: tuple[int, ...],
    checkpoint_kind: str,
    validation_split_name: str | None = None,
    evaluation_interval: int | None = None,
    evaluation_confidence_threshold: float | None = None,
    evaluation_nms_threshold: float | None = None,
    epoch_history: list[dict[str, object]] | None = None,
    validation_history: list[dict[str, object]] | None = None,
    best_metric_name: str | None = None,
    best_metric_value: float | None = None,
    warm_start_summary: dict[str, object] | None = None,
    best_checkpoint_state: dict[str, object] | None = None,
) -> dict[str, object]:
    """构建一个可直接序列化保存的 YOLOX checkpoint 状态。"""

    checkpoint_state = {
        "epoch": epoch,
        "model": {
            key: value.detach().cpu()
            for key, value in model.state_dict().items()
        },
        "optimizer": optimizer.state_dict(),
        "metric_name": metric_name,
        "metric_value": metric_value,
        "checkpoint_kind": checkpoint_kind,
        "category_names": list(category_names),
        "model_scale": model_scale,
        "input_size": list(input_size),
        "precision": precision,
        "gpu_count": gpu_count,
        "device_ids": list(device_ids),
        "validation_split_name": validation_split_name,
        "evaluation_interval": evaluation_interval,
        "evaluation_confidence_threshold": evaluation_confidence_threshold,
        "evaluation_nms_threshold": evaluation_nms_threshold,
    }
    if epoch_history is not None:
        checkpoint_state["epoch_history"] = [dict(item) for item in epoch_history]
    if validation_history is not None:
        checkpoint_state["validation_history"] = [dict(item) for item in validation_history]
    if best_metric_name is not None:
        checkpoint_state["best_metric_name"] = best_metric_name
    if best_metric_value is not None:
        checkpoint_state["best_metric_value"] = best_metric_value
    if warm_start_summary is not None:
        checkpoint_state["warm_start_summary"] = dict(warm_start_summary)
    if best_checkpoint_state is not None:
        checkpoint_state["best_checkpoint_state"] = best_checkpoint_state
    return checkpoint_state


def run_yolox_training_loop(request: YoloXTrainingLoopRequest) -> YoloXTrainingLoopResult:
    """执行 YOLOX epoch/batch 训练循环和验证编排。"""

    epoch_history = [dict(item) for item in request.epoch_history or []]
    validation_epoch_history = [
        dict(item)
        for item in request.validation_epoch_history or []
    ]
    best_metric_name = request.best_metric_name or (
        "val_map50_95" if request.validation_loader is not None else "train_total_loss"
    )
    best_metric_value = request.best_metric_value
    if best_metric_value is None and request.validation_loader is None:
        best_metric_value = float("inf")
    best_checkpoint_state = (
        dict(request.best_checkpoint_state)
        if request.best_checkpoint_state is not None
        else None
    )
    current_input_size = tuple(request.current_input_size)
    max_iterations = len(request.train_loader)
    total_iterations = request.max_epochs * max_iterations
    global_iter = request.start_epoch * max_iterations
    if request.model_ema is not None:
        request.model_ema.updates = global_iter

    set_yolox_training_loader_input_size(
        train_dataset=request.train_dataset,
        train_loader=request.train_loader,
        input_size=current_input_size,
    )
    for epoch_index in range(request.start_epoch, request.max_epochs):
        current_epoch = epoch_index + 1
        no_aug_enabled = is_yolox_no_aug_epoch(
            epoch=current_epoch,
            max_epochs=request.max_epochs,
            no_aug_epochs=request.no_aug_epochs,
        )
        set_yolox_training_loader_mosaic_enabled(
            train_dataset=request.train_dataset,
            train_loader=request.train_loader,
            enabled=not no_aug_enabled,
        )
        set_yolox_head_use_l1(model=request.training_model, enabled=no_aug_enabled)
        request.training_model.train()
        epoch_totals: dict[str, float] = {}
        epoch_iterations = 0
        train_iterator = iter(request.train_loader)
        for iteration_index in range(1, max_iterations + 1):
            images, targets, _image_infos, _image_ids = next(train_iterator)
            request.optimizer.zero_grad(set_to_none=True)
            images = images.to(device=request.device, dtype=request.torch_module.float32)
            targets = targets.to(device=request.device, dtype=request.torch_module.float32)
            images, targets = preprocess_yolox_training_batch(
                torch_module=request.torch_module,
                images=images,
                targets=targets,
                target_size=current_input_size,
            )

            with build_yolox_autocast_context(
                torch_module=request.torch_module,
                device=request.device,
                precision=request.precision,
            ):
                outputs = request.training_model(images, targets)
                total_loss = outputs["total_loss"]

            use_fp16 = request.precision == "fp16" and request.device.startswith("cuda")
            if use_fp16:
                request.grad_scaler.scale(total_loss).backward()
                request.grad_scaler.step(request.optimizer)
                request.grad_scaler.update()
            else:
                total_loss.backward()
                request.optimizer.step()

            learning_rate = request.scheduler.update_lr(global_iter + 1)
            for param_group in request.optimizer.param_groups:
                param_group["lr"] = learning_rate
            if request.model_ema is not None:
                request.model_ema.update(request.training_model)

            global_iter += 1
            epoch_iterations += 1
            scalar_outputs = convert_yolox_training_outputs(outputs)
            scalar_outputs["lr"] = float(learning_rate)
            for metric_name, metric_value in scalar_outputs.items():
                target_metric_name = metric_name if metric_name == "lr" else f"train_{metric_name}"
                epoch_totals[target_metric_name] = (
                    epoch_totals.get(target_metric_name, 0.0) + metric_value
                )
            if request.batch_callback is not None:
                request.batch_callback(
                    YoloXTrainingBatchProgress(
                        epoch=current_epoch,
                        max_epochs=request.max_epochs,
                        iteration=iteration_index,
                        max_iterations=max_iterations,
                        global_iteration=global_iter,
                        total_iterations=total_iterations,
                        input_size=current_input_size,
                        learning_rate=float(learning_rate),
                        train_metrics=build_yolox_batch_progress_metrics(scalar_outputs),
                    )
                )
            if request.multiscale_range > 0 and global_iter % 10 == 0:
                current_input_size = random_resize_yolox_input_size(
                    base_input_size=request.input_size,
                    multiscale_range=request.multiscale_range,
                    random_seed=request.random_seed + global_iter,
                )
                set_yolox_training_loader_input_size(
                    train_dataset=request.train_dataset,
                    train_loader=request.train_loader,
                    input_size=current_input_size,
                )

        epoch_metrics = {
            metric_name: metric_total / epoch_iterations
            for metric_name, metric_total in epoch_totals.items()
        }
        validation_metrics: dict[str, float] = {}
        validation_ran = False
        validation_snapshot: dict[str, object] | None = None
        evaluation_model = resolve_yolox_evaluation_model(
            training_model=request.training_model,
            model_ema=request.model_ema,
        )
        checkpoint_model = request.model_ema.ema if request.model_ema is not None else request.base_model
        if request.validation_loader is not None and request.validation_evaluator is not None:
            validation_ran = should_run_yolox_validation_evaluation(
                epoch=current_epoch,
                max_epochs=request.max_epochs,
                evaluation_interval=request.evaluation_interval,
            )
            if validation_ran:
                validation_metrics = request.validation_evaluator(evaluation_model)
            for metric_name, metric_value in validation_metrics.items():
                epoch_metrics[f"val_{metric_name}"] = metric_value
        epoch_metrics["epoch"] = current_epoch
        epoch_history.append(epoch_metrics)

        current_metric_value = _extract_current_metric_value(
            epoch_metrics=epoch_metrics,
            metric_name=best_metric_name,
        )
        if current_metric_value is not None and is_yolox_metric_improved(
            current_metric_value=current_metric_value,
            best_metric_value=best_metric_value,
            higher_is_better=request.validation_loader is not None,
        ):
            best_metric_value = current_metric_value
            best_checkpoint_state = build_yolox_checkpoint_state(
                model=checkpoint_model,
                optimizer=request.optimizer,
                epoch=current_epoch,
                metric_name=best_metric_name,
                metric_value=current_metric_value,
                category_names=request.train_category_names,
                model_scale=request.model_scale,
                input_size=request.input_size,
                precision=request.precision,
                gpu_count=request.gpu_count,
                device_ids=request.device_ids,
                checkpoint_kind="best",
                validation_split_name=request.validation_split_name,
                evaluation_interval=(
                    request.evaluation_interval if request.validation_loader is not None else None
                ),
                evaluation_confidence_threshold=(
                    request.evaluation_confidence_threshold
                    if request.validation_loader is not None
                    else None
                ),
                evaluation_nms_threshold=(
                    request.evaluation_nms_threshold
                    if request.validation_loader is not None
                    else None
                ),
            )

        if validation_ran:
            validation_epoch_history.append(
                {
                    "epoch": current_epoch,
                    **dict(validation_metrics),
                }
            )
            validation_snapshot = build_yolox_validation_metrics_payload(
                enabled=True,
                split_name=request.validation_split_name,
                sample_count=request.validation_sample_count,
                evaluation_interval=request.evaluation_interval,
                confidence_threshold=request.evaluation_confidence_threshold,
                nms_threshold=request.evaluation_nms_threshold,
                best_metric_name="map50_95",
                best_metric_value=best_metric_value,
                validation_history=validation_epoch_history,
            )

        train_metrics_snapshot = build_yolox_train_metrics_payload(
            device=request.device,
            gpu_count=request.gpu_count,
            device_ids=request.device_ids,
            distributed_mode=request.distributed_mode,
            precision=request.precision,
            batch_size=request.batch_size,
            max_epochs=request.max_epochs,
            evaluation_interval=request.evaluation_interval,
            input_size=request.input_size,
            train_split_name=request.train_split_name,
            validation_split_name=request.validation_split_name,
            sample_count=request.total_sample_count,
            train_sample_count=request.train_sample_count,
            validation_sample_count=request.validation_sample_count,
            category_names=request.train_category_names,
            best_metric_name=best_metric_name,
            best_metric_value=best_metric_value,
            final_metrics=epoch_metrics,
            epoch_history=epoch_history,
            parameter_count=int(request.parameter_count),
            warm_start_summary=request.warm_start_summary,
        )

        control_command = None
        if request.epoch_callback is not None:
            control_command = request.epoch_callback(
                YoloXTrainingEpochProgress(
                    epoch=current_epoch,
                    max_epochs=request.max_epochs,
                    evaluation_interval=request.evaluation_interval,
                    validation_ran=validation_ran,
                    evaluated_epochs=tuple(
                        current_epoch_metrics["epoch"]
                        for current_epoch_metrics in validation_epoch_history
                        if isinstance(current_epoch_metrics.get("epoch"), int)
                    ),
                    train_metrics=extract_yolox_train_progress_metrics(epoch_metrics),
                    validation_metrics=dict(validation_metrics),
                    train_metrics_snapshot=dict(train_metrics_snapshot),
                    validation_snapshot=(
                        dict(validation_snapshot) if validation_snapshot is not None else None
                    ),
                    current_metric_name=best_metric_name,
                    current_metric_value=current_metric_value,
                    best_metric_name=best_metric_name,
                    best_metric_value=best_metric_value,
                )
            )

        if control_command is not None and control_command.terminate_training:
            return YoloXTrainingLoopResult(status="terminated")

        if control_command is not None and (
            control_command.save_checkpoint or control_command.pause_training
        ):
            latest_checkpoint_state = build_yolox_checkpoint_state(
                model=checkpoint_model,
                optimizer=request.optimizer,
                epoch=current_epoch,
                metric_name=best_metric_name,
                metric_value=(
                    float(current_metric_value)
                    if current_metric_value is not None
                    else float(best_metric_value or 0.0)
                ),
                category_names=request.train_category_names,
                model_scale=request.model_scale,
                input_size=request.input_size,
                precision=request.precision,
                gpu_count=request.gpu_count,
                device_ids=request.device_ids,
                checkpoint_kind="latest",
                validation_split_name=request.validation_split_name,
                evaluation_interval=(
                    request.evaluation_interval if request.validation_loader is not None else None
                ),
                evaluation_confidence_threshold=(
                    request.evaluation_confidence_threshold
                    if request.validation_loader is not None
                    else None
                ),
                evaluation_nms_threshold=(
                    request.evaluation_nms_threshold
                    if request.validation_loader is not None
                    else None
                ),
                epoch_history=epoch_history,
                validation_history=validation_epoch_history,
                best_metric_name=best_metric_name,
                best_metric_value=best_metric_value,
                warm_start_summary=request.warm_start_summary,
                best_checkpoint_state=best_checkpoint_state,
            )
            savepoint = YoloXTrainingSavePoint(
                epoch=current_epoch,
                latest_checkpoint_bytes=serialize_yolox_checkpoint_bytes(
                    torch_module=request.torch_module,
                    checkpoint_state=latest_checkpoint_state,
                ),
                best_checkpoint_bytes=(
                    serialize_yolox_checkpoint_bytes(
                        torch_module=request.torch_module,
                        checkpoint_state=best_checkpoint_state,
                    )
                    if best_checkpoint_state is not None
                    else None
                ),
                best_metric_name=best_metric_name,
                best_metric_value=best_metric_value,
            )
            if request.savepoint_callback is not None:
                request.savepoint_callback(savepoint)
            if control_command.pause_training:
                return YoloXTrainingLoopResult(status="paused", savepoint=savepoint)

    if best_checkpoint_state is None or best_metric_value is None:
        raise ServiceConfigurationError("YOLOX 训练没有生成有效 checkpoint")

    final_metrics = dict(epoch_history[-1]) if epoch_history else {}
    raw_final_metric_value = final_metrics.get(best_metric_name)
    if isinstance(raw_final_metric_value, int | float):
        final_metric_value = float(raw_final_metric_value)
    else:
        final_metric_value = float(best_metric_value)
    checkpoint_model = request.model_ema.ema if request.model_ema is not None else request.base_model
    latest_checkpoint_state = build_yolox_checkpoint_state(
        model=checkpoint_model,
        optimizer=request.optimizer,
        epoch=request.max_epochs,
        metric_name=best_metric_name,
        metric_value=final_metric_value,
        category_names=request.train_category_names,
        model_scale=request.model_scale,
        input_size=request.input_size,
        precision=request.precision,
        gpu_count=request.gpu_count,
        device_ids=request.device_ids,
        checkpoint_kind="latest",
        validation_split_name=request.validation_split_name,
        evaluation_interval=(
            request.evaluation_interval if request.validation_loader is not None else None
        ),
        evaluation_confidence_threshold=(
            request.evaluation_confidence_threshold
            if request.validation_loader is not None
            else None
        ),
        evaluation_nms_threshold=(
            request.evaluation_nms_threshold if request.validation_loader is not None else None
        ),
    )

    validation_metrics_payload = build_yolox_validation_metrics_payload(
        enabled=request.validation_loader is not None,
        split_name=request.validation_split_name,
        sample_count=request.validation_sample_count,
        evaluation_interval=(
            request.evaluation_interval if request.validation_loader is not None else None
        ),
        confidence_threshold=(
            request.evaluation_confidence_threshold
            if request.validation_loader is not None
            else None
        ),
        nms_threshold=(
            request.evaluation_nms_threshold if request.validation_loader is not None else None
        ),
        best_metric_name="map50_95" if request.validation_loader is not None else None,
        best_metric_value=best_metric_value if request.validation_loader is not None else None,
        validation_history=validation_epoch_history,
    )
    metrics_payload = build_yolox_train_metrics_payload(
        device=request.device,
        gpu_count=request.gpu_count,
        device_ids=request.device_ids,
        distributed_mode=request.distributed_mode,
        precision=request.precision,
        batch_size=request.batch_size,
        max_epochs=request.max_epochs,
        evaluation_interval=request.evaluation_interval,
        input_size=request.input_size,
        train_split_name=request.train_split_name,
        validation_split_name=request.validation_split_name,
        sample_count=request.total_sample_count,
        train_sample_count=request.train_sample_count,
        validation_sample_count=request.validation_sample_count,
        category_names=request.train_category_names,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        final_metrics=final_metrics,
        epoch_history=epoch_history,
        parameter_count=int(request.parameter_count),
        warm_start_summary=request.warm_start_summary,
    )
    return YoloXTrainingLoopResult(
        status="completed",
        checkpoint_bytes=serialize_yolox_checkpoint_bytes(
            torch_module=request.torch_module,
            checkpoint_state=best_checkpoint_state,
        ),
        latest_checkpoint_bytes=serialize_yolox_checkpoint_bytes(
            torch_module=request.torch_module,
            checkpoint_state=latest_checkpoint_state,
        ),
        metrics_payload=metrics_payload,
        validation_metrics_payload=validation_metrics_payload,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        final_metrics=final_metrics,
    )


def extract_yolox_train_progress_metrics(epoch_metrics: dict[str, object]) -> dict[str, float]:
    """从单轮指标中提取训练阶段进度展示指标。"""

    train_metrics = _extract_prefixed_metrics(epoch_metrics, prefix="train_")
    learning_rate = epoch_metrics.get("lr")
    if isinstance(learning_rate, int | float):
        train_metrics["lr"] = float(learning_rate)
    return train_metrics


def _extract_current_metric_value(
    *,
    epoch_metrics: dict[str, object],
    metric_name: str,
) -> float | None:
    """从当前 epoch 指标中读取用于 best checkpoint 比较的数值。"""

    metric_value = epoch_metrics.get(metric_name)
    if isinstance(metric_value, int | float):
        return float(metric_value)
    return None


def _extract_prefixed_metrics(
    epoch_metrics: dict[str, object],
    *,
    prefix: str,
) -> dict[str, float]:
    """从单轮指标中提取指定前缀的浮点指标。"""

    extracted_metrics: dict[str, float] = {}
    for key, value in epoch_metrics.items():
        if not key.startswith(prefix):
            continue
        if isinstance(value, int | float):
            extracted_metrics[key.removeprefix(prefix)] = float(value)
    return extracted_metrics


def build_yolox_validation_metrics_payload(
    *,
    enabled: bool,
    split_name: str | None,
    sample_count: int,
    evaluation_interval: int | None,
    confidence_threshold: float | None,
    nms_threshold: float | None,
    best_metric_name: str | None,
    best_metric_value: float | None,
    validation_history: list[dict[str, object]],
) -> dict[str, object]:
    """构建 YOLOX validation-metrics.json 对应载荷。"""

    validation_final_metrics = dict(validation_history[-1]) if validation_history else {}
    evaluated_epochs = [
        epoch_metrics["epoch"]
        for epoch_metrics in validation_history
        if isinstance(epoch_metrics.get("epoch"), int)
    ]
    return {
        "enabled": enabled,
        "split_name": split_name,
        "sample_count": sample_count,
        "evaluation_interval": evaluation_interval,
        "confidence_threshold": confidence_threshold,
        "nms_threshold": nms_threshold,
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "final_metrics": validation_final_metrics,
        "evaluated_epochs": evaluated_epochs,
        "epoch_history": [dict(item) for item in validation_history],
    }


def should_run_yolox_validation_evaluation(
    *,
    epoch: int,
    max_epochs: int,
    evaluation_interval: int,
) -> bool:
    """判断当前轮是否需要执行真实验证评估。"""

    if epoch >= max_epochs:
        return True
    return epoch % max(1, evaluation_interval) == 0


def is_yolox_metric_improved(
    *,
    current_metric_value: float,
    best_metric_value: float | None,
    higher_is_better: bool,
) -> bool:
    """按指标方向判断当前轮是否刷新最佳结果。"""

    if best_metric_value is None:
        return True
    if higher_is_better:
        return current_metric_value >= best_metric_value
    return current_metric_value <= best_metric_value


def build_yolox_train_metrics_payload(
    *,
    device: str,
    gpu_count: int,
    device_ids: tuple[int, ...],
    distributed_mode: str,
    precision: str,
    batch_size: int,
    max_epochs: int,
    evaluation_interval: int,
    input_size: tuple[int, int],
    train_split_name: str,
    validation_split_name: str | None,
    sample_count: int,
    train_sample_count: int,
    validation_sample_count: int,
    category_names: tuple[str, ...],
    best_metric_name: str,
    best_metric_value: float | None,
    final_metrics: dict[str, object],
    epoch_history: list[dict[str, object]],
    parameter_count: int,
    warm_start_summary: dict[str, object],
) -> dict[str, object]:
    """构建 YOLOX train-metrics.json 对应载荷。"""

    return {
        "implementation_mode": YOLOX_DETECTION_CORE_IMPLEMENTATION_MODE,
        "device": device,
        "gpu_count": gpu_count,
        "device_ids": list(device_ids),
        "distributed_mode": distributed_mode,
        "precision": precision,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "evaluation_interval": evaluation_interval,
        "input_size": list(input_size),
        "train_split_name": train_split_name,
        "validation_split_name": validation_split_name,
        "sample_count": sample_count,
        "train_sample_count": train_sample_count,
        "validation_sample_count": validation_sample_count,
        "category_names": list(category_names),
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "final_metrics": dict(final_metrics),
        "epoch_history": [dict(item) for item in epoch_history],
        "parameter_count": parameter_count,
        "warm_start": dict(warm_start_summary),
    }


def convert_yolox_training_outputs(outputs: dict[str, object]) -> dict[str, float]:
    """把 YOLOX forward 输出转换为可序列化的标量字典。"""

    scalar_outputs: dict[str, float] = {}
    for key, value in outputs.items():
        if hasattr(value, "detach"):
            scalar_outputs[key] = float(value.detach().cpu().item())
        elif isinstance(value, int | float):
            scalar_outputs[key] = float(value)
    return scalar_outputs


def _validate_resume_validation_configuration(
    *,
    checkpoint_payload: dict[str, object],
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
) -> None:
    """校验 resume checkpoint 中记录的 validation 配置是否与当前任务一致。"""

    checkpoint_validation_split_name = checkpoint_payload.get("validation_split_name")
    if checkpoint_validation_split_name != expected_validation_split_name:
        raise InvalidRequestError("resume checkpoint 的 validation_split_name 与当前任务不一致")

    if expected_validation_split_name is None:
        return

    checkpoint_evaluation_interval = checkpoint_payload.get("evaluation_interval")
    if (
        not isinstance(checkpoint_evaluation_interval, int)
        or checkpoint_evaluation_interval != expected_evaluation_interval
    ):
        raise InvalidRequestError("resume checkpoint 的 evaluation_interval 与当前任务不一致")

    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_confidence_threshold"),
        expected_value=expected_evaluation_confidence_threshold,
        field_name="evaluation_confidence_threshold",
    )
    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_nms_threshold"),
        expected_value=expected_evaluation_nms_threshold,
        field_name="evaluation_nms_threshold",
    )


def _assert_resume_optional_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float | None,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的可选浮点配置与当前任务一致。"""

    if expected_value is None:
        if checkpoint_value is not None:
            raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前任务不一致")
        return

    if not isinstance(checkpoint_value, int | float) or not math.isclose(
        float(checkpoint_value),
        float(expected_value),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前任务不一致")


def _read_float_option(extra_options: dict[str, object], key: str, *, default: float) -> float:
    """从 extra_options 中读取可选浮点数。"""

    value = extra_options.get(key)
    if isinstance(value, int | float):
        return float(value)
    return default


def _read_int_option(extra_options: dict[str, object], key: str, *, default: int) -> int:
    """从 extra_options 中读取可选整数。"""

    value = extra_options.get(key)
    if isinstance(value, int):
        return value
    return default
