"""RF-DETR Lightning 训练运行前的轻量初始化。"""

from __future__ import annotations

import sys
import types

_MODEL_SUMMARY_MODULE = "pytorch_lightning.callbacks.model_summary"
_RICH_MODEL_SUMMARY_MODULE = "pytorch_lightning.callbacks.rich_model_summary"
_DISABLED_MARKER = "__amvision_rfdetr_model_summary_disabled__"


class DisabledLightningModelSummary:
    """RF-DETR 平台训练禁用 Lightning model summary。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "RF-DETR 平台训练已禁用 Lightning model summary；"
            "本项目不执行 FLOP 统计，也不依赖 Triton。"
        )


class DisabledLightningRichModelSummary(DisabledLightningModelSummary):
    """RF-DETR 平台训练禁用 Lightning rich model summary。"""


def disable_lightning_model_summary_import() -> None:
    """禁用 Lightning 的 model summary 导入分支，避免触发 PyTorch FLOP 统计依赖。"""

    if _MODEL_SUMMARY_MODULE not in sys.modules:
        model_summary_module = types.ModuleType(_MODEL_SUMMARY_MODULE)
        model_summary_module.ModelSummary = DisabledLightningModelSummary
        setattr(model_summary_module, _DISABLED_MARKER, True)
        sys.modules[_MODEL_SUMMARY_MODULE] = model_summary_module

    if _RICH_MODEL_SUMMARY_MODULE not in sys.modules:
        rich_summary_module = types.ModuleType(_RICH_MODEL_SUMMARY_MODULE)
        rich_summary_module.RichModelSummary = DisabledLightningRichModelSummary
        setattr(rich_summary_module, _DISABLED_MARKER, True)
        sys.modules[_RICH_MODEL_SUMMARY_MODULE] = rich_summary_module
