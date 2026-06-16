"""RF-DETR 训练 checkpoint 格式转换工具。"""

from __future__ import annotations

import logging
from typing import Any

import torch

logger = logging.getLogger(__name__)

__all__ = ["convert_legacy_checkpoint"]


def convert_legacy_checkpoint(old_path: str, new_path: str) -> None:
    """把 RF-DETR 早期 .pth checkpoint 转成 Lightning 可恢复格式。"""
    old: dict[str, Any] = torch.load(old_path, map_location="cpu", weights_only=False)

    if "model" not in old:
        raise ValueError(
            f"The checkpoint at {old_path!r} does not contain a 'model' key."
            " Only RF-DETR early .pth files produced by engine.py are supported."
        )

    args_obj = old.get("args")
    if isinstance(args_obj, dict):
        hyper_parameters: dict[str, Any] = args_obj
    elif args_obj is None:
        hyper_parameters = {}
    else:
        try:
            hyper_parameters = vars(args_obj)
        except TypeError:
            logger.warning(
                "Cannot extract hyper_parameters from args of type %s; storing empty dict.",
                type(args_obj).__name__,
            )
            hyper_parameters = {}

    new: dict[str, Any] = {
        "state_dict": {"model." + k: v for k, v in old["model"].items()},
        "epoch": old.get("epoch", 0),
        "global_step": 0,
        "hyper_parameters": hyper_parameters,
        "legacy_checkpoint_format": True,
    }

    if "ema_model" in old:
        new["legacy_ema_state_dict"] = old["ema_model"]

    torch.save(new, new_path)


