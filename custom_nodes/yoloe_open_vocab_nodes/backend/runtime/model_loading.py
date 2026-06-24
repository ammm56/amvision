"""YOLOE runtime checkpoint 与模型加载 helper。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import torch

from backend.service.application.errors import InvalidRequestError
from custom_nodes.yoloe_open_vocab_nodes.backend.core.nn.models import (
    YoloePromptFreeSegmentationModel,
    YoloeTextPromptSegmentationModel,
    build_yoloe_prompt_free_segmentation_model,
    build_yoloe_text_prompt_segmentation_model,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.core.weights.checkpoint import (
    is_ignored_text_prompt_checkpoint_key,
    load_prompt_free_checkpoint_artifacts,
)


def load_prompt_free_model_from_checkpoint(
    *,
    variant: Any,
    device_name: str,
    precision: str,
) -> tuple[YoloePromptFreeSegmentationModel, Any]:
    """加载 prompt-free checkpoint 并返回可推理模型和 artifact。"""

    artifacts = load_prompt_free_checkpoint_artifacts(checkpoint_path=variant.checkpoint_path)
    model = build_yoloe_prompt_free_segmentation_model(
        model_name=variant.model_name,
        model_scale=artifacts.model_scale,
        num_classes=len(artifacts.class_names),
        model_config=artifacts.model_config,
        input_channels=int(artifacts.model_config.get("ch", 3)),
    )
    incompatible = model.load_state_dict(artifacts.state_dict, strict=False)
    _raise_for_incompatible_state_dict(
        incompatible=incompatible,
        checkpoint_path=variant.checkpoint_path,
        mode_name="prompt-free",
        ignored_key_predicate=None,
    )
    _prepare_loaded_model(
        model=model,
        class_names=artifacts.class_names,
        device_name=device_name,
        precision=precision,
    )
    return model, artifacts


def load_text_prompt_model_from_checkpoint(
    *,
    variant: Any,
    device_name: str,
    precision: str,
    mode_name: str,
) -> tuple[YoloeTextPromptSegmentationModel, Any]:
    """加载 text/visual prompt checkpoint 并返回可推理模型和 artifact。"""

    artifacts = load_prompt_free_checkpoint_artifacts(checkpoint_path=variant.checkpoint_path)
    model = build_yoloe_text_prompt_segmentation_model(
        model_name=variant.model_name,
        model_scale=artifacts.model_scale,
        num_classes=len(artifacts.class_names),
        model_config=artifacts.model_config,
        input_channels=int(artifacts.model_config.get("ch", 3)),
    )
    incompatible = model.load_state_dict(artifacts.state_dict, strict=False)
    _raise_for_incompatible_state_dict(
        incompatible=incompatible,
        checkpoint_path=variant.checkpoint_path,
        mode_name=mode_name,
        ignored_key_predicate=is_ignored_text_prompt_checkpoint_key,
    )
    _prepare_loaded_model(
        model=model,
        class_names=artifacts.class_names,
        device_name=device_name,
        precision=precision,
    )
    return model, artifacts


def _raise_for_incompatible_state_dict(
    *,
    incompatible: Any,
    checkpoint_path: Any,
    mode_name: str,
    ignored_key_predicate: Callable[[str], bool] | None,
) -> None:
    """把 state_dict 加载差异转成节点可读错误。"""

    unexpected_keys = tuple(
        key
        for key in incompatible.unexpected_keys
        if ignored_key_predicate is None or not ignored_key_predicate(key)
    )
    missing_keys = tuple(
        key for key in incompatible.missing_keys if ignored_key_predicate is None or not ignored_key_predicate(key)
    )
    if unexpected_keys or missing_keys:
        raise InvalidRequestError(
            f"YOLOE {mode_name} checkpoint 与 project-native 模型结构不兼容",
            details={
                "checkpoint_path": str(checkpoint_path),
                "unexpected_keys": list(unexpected_keys),
                "missing_keys": list(missing_keys),
            },
        )


def _prepare_loaded_model(
    *,
    model: Any,
    class_names: dict[int, str],
    device_name: str,
    precision: str,
) -> None:
    """设置 runtime 推理需要的通用模型属性。"""

    model.names = dict(class_names)
    model.stride = torch.tensor((8.0, 16.0, 32.0), dtype=torch.float32)
    model.to(device_name)
    if precision == "fp16":
        model.half()
    model.eval()


__all__ = [
    "load_prompt_free_model_from_checkpoint",
    "load_text_prompt_model_from_checkpoint",
]
