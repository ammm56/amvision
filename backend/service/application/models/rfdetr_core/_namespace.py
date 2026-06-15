"""RF-DETR core 核心处理模块：`_namespace`。"""

import dataclasses
import types

from backend.service.application.models.rfdetr_core.utilities.decorators import deprecated

from backend.service.application.models.rfdetr_core.config import ModelConfig, TrainConfig
from backend.service.application.models.rfdetr_core.models._defaults import MODEL_DEFAULTS, ModelDefaults

_MC_NAMESPACE_FIELDS = {
    "amp",
    "backbone_lora",
    "bbox_reparam",
    "ca_nheads",
    "dec_layers",
    "dec_n_points",
    "device",
    "encoder",
    "freeze_encoder",
    "gradient_checkpointing",
    "group_detr",
    "hidden_dim",
    "ia_bce_loss",
    "layer_norm",
    "lite_refpoint_refine",
    "mask_downsample_ratio",
    "num_channels",
    "num_classes",
    "num_queries",
    "num_select",
    "num_windows",
    "out_feature_indexes",
    "patch_size",
    "positional_encoding_size",
    "pretrain_weights",
    "projector_scale",
    "resolution",
    "sa_nheads",
    "segmentation_head",
    "two_stage",
}

#
_TC_NON_NAMESPACE_FIELDS = {
    "resume",
    "seed",
    "cls_loss_coef",
    "group_detr",
    "ia_bce_loss",
    "segmentation_head",
    "num_select",
    "accelerator",
    "strategy",
    "devices",
    "num_nodes",
    "tensorboard",
    "auto_batch_target_effective",
    "auto_batch_max_targets_per_image",
    "auto_batch_ema_headroom",
    "progress_bar",
    "run_test",
    "dont_save_weights",
    "pin_memory",
    "persistent_workers",
    "lr_scheduler",
    "lr_min_factor",
    "class_names",
}

_TC_NAMESPACE_FIELDS = set(TrainConfig.model_fields) - _TC_NON_NAMESPACE_FIELDS


def _namespace_from_configs(
    model_config: ModelConfig,
    train_config: TrainConfig,
    defaults: ModelDefaults = MODEL_DEFAULTS,
) -> types.SimpleNamespace:
    """执行 `_namespace_from_configs`。
    
    参数：
    - `model_config`：传入的 `model_config` 参数。
    - `train_config`：传入的 `train_config` 参数。
    - `defaults`：传入的 `defaults` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    mc = model_config
    tc = train_config
    d = defaults
    train_fields_set = getattr(tc, "model_fields_set", set())
    model_fields_set = getattr(mc, "model_fields_set", set())
    cls_loss_coef = (
        tc.cls_loss_coef
        if "cls_loss_coef" in train_fields_set or "cls_loss_coef" not in model_fields_set
        else mc.cls_loss_coef
    )

    return types.SimpleNamespace(
        **{
            **dataclasses.asdict(d),
            **tc.model_dump(include=set(_TC_NAMESPACE_FIELDS)),
            **mc.model_dump(include=set(_MC_NAMESPACE_FIELDS)),
            "mask_ce_loss_coef": getattr(tc, "mask_ce_loss_coef", 5.0),
            "mask_dice_loss_coef": getattr(tc, "mask_dice_loss_coef", 5.0),
            "mask_point_sample_ratio": getattr(tc, "mask_point_sample_ratio", 16),
            "cls_loss_coef": cls_loss_coef,
            "resume": tc.resume or "",
            "seed": tc.seed if tc.seed is not None else 42,
        }
    )


@deprecated(target=_namespace_from_configs, deprecated_in="1.7.0", remove_in="1.9.0")
def build_namespace(model_config: ModelConfig, train_config: TrainConfig) -> types.SimpleNamespace:
    """执行 `build_namespace`。
    
    参数：
    - `model_config`：传入的 `model_config` 参数。
    - `train_config`：传入的 `train_config` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    ...
