"""RF-DETR training 子包的延迟导出入口。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "BestModelCallback": (
        "backend.service.application.models.rfdetr_core.training.callbacks",
        "BestModelCallback",
    ),
    "COCOEvalCallback": (
        "backend.service.application.models.rfdetr_core.training.callbacks",
        "COCOEvalCallback",
    ),
    "DropPathCallback": (
        "backend.service.application.models.rfdetr_core.training.callbacks",
        "DropPathCallback",
    ),
    "RFDETREMACallback": (
        "backend.service.application.models.rfdetr_core.training.callbacks",
        "RFDETREMACallback",
    ),
    "RFDETREarlyStopping": (
        "backend.service.application.models.rfdetr_core.training.callbacks",
        "RFDETREarlyStopping",
    ),
    "convert_legacy_checkpoint": (
        "backend.service.application.models.rfdetr_core.training.checkpoint",
        "convert_legacy_checkpoint",
    ),
    "RFDETRDataModule": (
        "backend.service.application.models.rfdetr_core.training.module_data",
        "RFDETRDataModule",
    ),
    "RFDETRModelModule": (
        "backend.service.application.models.rfdetr_core.training.module_model",
        "RFDETRModelModule",
    ),
    "build_trainer": (
        "backend.service.application.models.rfdetr_core.training.trainer",
        "build_trainer",
    ),
    "seed_everything": ("pytorch_lightning", "seed_everything"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """按需加载 RF-DETR training 子模块，避免导入时提前拉起重依赖。"""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
