"""YOLO11 segmentation 训练依赖导入。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import ServiceConfigurationError


@dataclass(frozen=True)
class Yolo11SegmentationTrainingImports:
    """描述 YOLO11 segmentation 训练需要的本地模块。"""

    cv2: Any
    np: Any
    torch: Any


def require_yolo11_segmentation_training_imports() -> Yolo11SegmentationTrainingImports:
    """导入 YOLO11 segmentation 训练依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except ImportError as exc:
        raise ServiceConfigurationError(
            "YOLO11 segmentation 训练缺少必要依赖",
            details={"missing": str(exc)},
        ) from exc
    return Yolo11SegmentationTrainingImports(cv2=cv2, np=np, torch=torch)


def resolve_yolo11_segmentation_training_device(
    *,
    torch_module: Any,
    extra_options: dict[str, object] | None,
) -> str:
    """根据训练参数解析 YOLO11 segmentation 训练设备。"""

    requested = str((extra_options or {}).get("device", "cpu")).strip().lower()
    if requested == "cuda" and torch_module.cuda.is_available():
        return "cuda:0"
    if requested.startswith("cuda:") and torch_module.cuda.is_available():
        return requested
    return "cpu"


def build_yolo11_segmentation_autocast_context(
    *,
    torch_module: Any,
    precision: str,
    device_name: str,
) -> Any:
    """构建 YOLO11 segmentation 训练使用的 autocast context。"""

    if precision == "fp16" and "cuda" in device_name:
        return torch_module.amp.autocast(device_name)
    return nullcontext()


__all__ = [
    "Yolo11SegmentationTrainingImports",
    "build_yolo11_segmentation_autocast_context",
    "require_yolo11_segmentation_training_imports",
    "resolve_yolo11_segmentation_training_device",
]
