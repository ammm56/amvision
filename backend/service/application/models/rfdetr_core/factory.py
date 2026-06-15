"""RF-DETR core 模型构建模块：`factory`。"""

from __future__ import annotations

import warnings
from dataclasses import replace
from types import SimpleNamespace
from typing import TypeAlias

import torch.nn as nn
import torch

from backend.service.application.models.rfdetr_core._namespace import (
    _namespace_from_configs,
)
from backend.service.application.models.rfdetr_core.config import (
    ModelConfig,
    PretrainWeightsCompatibilityWarning,
    RFDETRBaseConfig,
    RFDETRLargeDeprecatedConfig,
    RFDETRLargeConfig,
    RFDETRMediumConfig,
    RFDETRNanoConfig,
    RFDETRSeg2XLargeConfig,
    RFDETRSegLargeConfig,
    RFDETRSegMediumConfig,
    RFDETRSegNanoConfig,
    RFDETRSegPreviewConfig,
    RFDETRSegSmallConfig,
    RFDETRSegXLargeConfig,
    RFDETRSmallConfig,
    TrainConfig,
)
from backend.service.application.models.rfdetr_core.models._defaults import (
    MODEL_DEFAULTS,
    ModelDefaults,
)
from backend.service.application.models.rfdetr_core.models.lwdetr import (
    build_model_from_config,
)
from backend.service.application.models.rfdetr_core.models.weights import (
    load_pretrain_weights,
)
from backend.service.application.models.rfdetr_core.utilities.state_dict import (
    _ckpt_args_get,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    ModelTaskType,
)

RfdetrConfigClass: TypeAlias = type[ModelConfig]

PROJECT_RFDETR_MODEL_DEFAULTS: ModelDefaults = replace(
    MODEL_DEFAULTS,
    force_no_pretrain=True,
)

_SCALE_ALIASES: dict[str, str] = {
    "n": "nano",
    "nano": "nano",
    "base": "base",
    "s": "s",
    "small": "s",
    "m": "m",
    "medium": "m",
    "l": "l",
    "large": "l",
    "preview": "preview",
    "x": "x",
    "xl": "x",
    "xlarge": "x",
    "xxl": "xxl",
    "xxlarge": "xxl",
}

_DETECTION_CONFIG_BY_SCALE: dict[str, RfdetrConfigClass] = {
    "nano": RFDETRNanoConfig,
    "base": RFDETRBaseConfig,
    "s": RFDETRSmallConfig,
    "m": RFDETRMediumConfig,
    "l": RFDETRLargeConfig,
}

_SEGMENTATION_CONFIG_BY_SCALE: dict[str, RfdetrConfigClass] = {
    "preview": RFDETRSegPreviewConfig,
    "nano": RFDETRSegNanoConfig,
    "s": RFDETRSegSmallConfig,
    "m": RFDETRSegMediumConfig,
    "l": RFDETRSegLargeConfig,
    "x": RFDETRSegXLargeConfig,
    "xxl": RFDETRSeg2XLargeConfig,
}
_DETECTION_CHECKPOINT_CONFIG_CANDIDATES: tuple[RfdetrConfigClass, ...] = (
    RFDETRNanoConfig,
    RFDETRSmallConfig,
    RFDETRMediumConfig,
    RFDETRLargeConfig,
    RFDETRLargeDeprecatedConfig,
)
_CHECKPOINT_ARCHITECTURE_FIELDS = (
    "encoder",
    "hidden_dim",
    "resolution",
    "patch_size",
    "num_windows",
    "dec_layers",
    "sa_nheads",
    "ca_nheads",
    "dec_n_points",
)


def normalize_rfdetr_full_core_scale(model_scale: str) -> str:
    """执行 `normalize_rfdetr_full_core_scale`。
    
    参数：
    - `model_scale`：传入的 `model_scale` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized = _SCALE_ALIASES.get(model_scale.strip().lower())
    if normalized is None:
        raise ValueError(f"RF-DETR full core 不支持 model_scale={model_scale!r}")
    return normalized


def resolve_rfdetr_full_core_input_divisor(
    *,
    task_type: ModelTaskType,
    model_scale: str,
) -> int:
    """执行 `resolve_rfdetr_full_core_input_divisor`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    config_cls = resolve_rfdetr_full_core_config_class(
        task_type=task_type,
        model_scale=model_scale,
    )
    patch_size = _read_int_config_default(config_cls, "patch_size")
    num_windows = _read_int_config_default(config_cls, "num_windows")
    return patch_size * num_windows


def align_rfdetr_full_core_input_size(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    input_size: tuple[int, int],
) -> tuple[int, int]:
    """执行 `align_rfdetr_full_core_input_size`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `input_size`：传入的 `input_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    first_dim, second_dim = input_size
    divisor = resolve_rfdetr_full_core_input_divisor(
        task_type=task_type,
        model_scale=model_scale,
    )
    return (
        _align_positive_dimension(first_dim, divisor),
        _align_positive_dimension(second_dim, divisor),
    )


def is_rfdetr_full_core_input_size_aligned(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    input_size: tuple[int, int],
) -> bool:
    """执行 `is_rfdetr_full_core_input_size_aligned`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `input_size`：传入的 `input_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    first_dim, second_dim = input_size
    divisor = resolve_rfdetr_full_core_input_divisor(
        task_type=task_type,
        model_scale=model_scale,
    )
    return first_dim % divisor == 0 and second_dim % divisor == 0


def resolve_rfdetr_full_core_config_class(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    pretrained_path: str | None = None,
) -> RfdetrConfigClass:
    """执行 `resolve_rfdetr_full_core_config_class`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    normalized_scale = normalize_rfdetr_full_core_scale(model_scale)
    config_map = _resolve_config_map(task_type)
    config_cls = config_map.get(normalized_scale)
    if config_cls is None:
        raise ValueError(
            f"RF-DETR full core 的 {task_type} 任务不支持 model_scale={model_scale!r}"
        )
    checkpoint_config_cls = _resolve_checkpoint_config_class(
        task_type=task_type,
        pretrained_path=pretrained_path,
    )
    if checkpoint_config_cls is not None:
        return checkpoint_config_cls
    return config_cls


def build_rfdetr_full_core_config(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    num_classes: int,
    pretrained_path: str | None = None,
    device: str = "cpu",
) -> ModelConfig:
    """执行 `build_rfdetr_full_core_config`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    - `device`：传入的 `device` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    config_cls = resolve_rfdetr_full_core_config_class(
        task_type=task_type,
        model_scale=model_scale,
        pretrained_path=pretrained_path,
    )
    with warnings.catch_warnings():
        if pretrained_path is None:
            warnings.filterwarnings(
                "ignore",
                category=PretrainWeightsCompatibilityWarning,
            )
        return config_cls(
            num_classes=num_classes,
            pretrain_weights=pretrained_path,
            device=device,
        )


def build_rfdetr_full_core_namespace(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    num_classes: int,
    pretrained_path: str | None = None,
    device: str = "cpu",
    dataset_dir: str = ".",
    output_dir: str = ".",
    defaults: ModelDefaults = PROJECT_RFDETR_MODEL_DEFAULTS,
) -> SimpleNamespace:
    """执行 `build_rfdetr_full_core_namespace`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    - `device`：传入的 `device` 参数。
    - `dataset_dir`：传入的 `dataset_dir` 参数。
    - `output_dir`：传入的 `output_dir` 参数。
    - `defaults`：传入的 `defaults` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    model_config = build_rfdetr_full_core_config(
        task_type=task_type,
        model_scale=model_scale,
        num_classes=num_classes,
        pretrained_path=pretrained_path,
        device=device,
    )
    train_config = TrainConfig(dataset_dir=dataset_dir, output_dir=output_dir)
    return _namespace_from_configs(model_config, train_config, defaults)


def build_rfdetr_full_core_model(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    num_classes: int,
    pretrained_path: str | None = None,
    device: str = "cpu",
    load_pretrained: bool = True,
    defaults: ModelDefaults = PROJECT_RFDETR_MODEL_DEFAULTS,
) -> nn.Module:
    """执行 `build_rfdetr_full_core_model`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `model_scale`：传入的 `model_scale` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    - `device`：传入的 `device` 参数。
    - `load_pretrained`：传入的 `load_pretrained` 参数。
    - `defaults`：传入的 `defaults` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    model_config = build_rfdetr_full_core_config(
        task_type=task_type,
        model_scale=model_scale,
        num_classes=num_classes,
        pretrained_path=pretrained_path,
        device=device,
    )
    train_config = TrainConfig(dataset_dir=".", output_dir=".")
    model = build_model_from_config(model_config, train_config, defaults=defaults)
    if pretrained_path and load_pretrained:
        load_pretrain_weights(model, model_config)
    return model


def _resolve_config_map(task_type: ModelTaskType) -> dict[str, RfdetrConfigClass]:
    """执行 `_resolve_config_map`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if task_type == DETECTION_TASK_TYPE:
        return _DETECTION_CONFIG_BY_SCALE
    if task_type == SEGMENTATION_TASK_TYPE:
        return _SEGMENTATION_CONFIG_BY_SCALE
    raise ValueError(f"RF-DETR full core 暂不支持 task_type={task_type!r}")


def _resolve_checkpoint_config_class(
    *,
    task_type: ModelTaskType,
    pretrained_path: str | None,
) -> RfdetrConfigClass | None:
    """执行 `_resolve_checkpoint_config_class`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if pretrained_path is None:
        return None
    checkpoint_args = _read_checkpoint_args(pretrained_path)
    if checkpoint_args is None:
        return None
    for config_cls in _resolve_checkpoint_config_candidates(task_type):
        if _checkpoint_args_match_config(checkpoint_args, config_cls):
            return config_cls
    return None


def _read_checkpoint_args(pretrained_path: str) -> object | None:
    """执行 `_read_checkpoint_args`。
    
    参数：
    - `pretrained_path`：传入的 `pretrained_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    checkpoint = torch.load(pretrained_path, map_location="cpu", weights_only=False)
    if isinstance(checkpoint, dict):
        args = checkpoint.get("args")
        if args is not None:
            return args
        hyper_parameters = checkpoint.get("hyper_parameters")
        if hyper_parameters is not None:
            return hyper_parameters
    return None


def _resolve_checkpoint_config_candidates(
    task_type: ModelTaskType,
) -> tuple[RfdetrConfigClass, ...]:
    """执行 `_resolve_checkpoint_config_candidates`。
    
    参数：
    - `task_type`：传入的 `task_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if task_type == DETECTION_TASK_TYPE:
        return _DETECTION_CHECKPOINT_CONFIG_CANDIDATES
    if task_type == SEGMENTATION_TASK_TYPE:
        return tuple(_SEGMENTATION_CONFIG_BY_SCALE.values())
    return ()


def _checkpoint_args_match_config(
    checkpoint_args: object,
    config_cls: RfdetrConfigClass,
) -> bool:
    """执行 `_checkpoint_args_match_config`。
    
    参数：
    - `checkpoint_args`：传入的 `checkpoint_args` 参数。
    - `config_cls`：传入的 `config_cls` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    checked_field_count = 0
    for field_name in _CHECKPOINT_ARCHITECTURE_FIELDS:
        checkpoint_value = _ckpt_args_get(checkpoint_args, field_name)
        if checkpoint_value is None:
            continue
        field_info = config_cls.model_fields.get(field_name)
        if field_info is None:
            return False
        checked_field_count += 1
        if checkpoint_value != field_info.default:
            return False
    return checked_field_count > 0


def _read_int_config_default(config_cls: RfdetrConfigClass, field_name: str) -> int:
    """执行 `_read_int_config_default`。
    
    参数：
    - `config_cls`：传入的 `config_cls` 参数。
    - `field_name`：传入的 `field_name` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    field_info = config_cls.model_fields[field_name]
    return int(field_info.default)


def _align_positive_dimension(value: int, divisor: int) -> int:
    """把正整数维度上取整到指定倍数。"""

    normalized_value = int(value)
    if normalized_value <= 0:
        raise ValueError("RF-DETR 输入尺寸必须大于 0")
    return ((normalized_value + divisor - 1) // divisor) * divisor
