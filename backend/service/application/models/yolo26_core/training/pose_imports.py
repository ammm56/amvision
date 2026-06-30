"""YOLO26 pose 训练依赖导入。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.training.device_selection import (
    resolve_single_training_device_name,
)


@dataclass(frozen=True)
class Yolo26PoseTrainingImports:
    """描述 YOLO26 pose 训练需要的本地模块。"""

    cv2: Any
    np: Any
    torch: Any


def require_yolo26_pose_training_imports() -> Yolo26PoseTrainingImports:
    """导入 YOLO26 pose 训练依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except ImportError as exc:
        raise ServiceConfigurationError(
            "YOLO26 pose 训练缺少必要依赖",
            details={"missing": str(exc)},
        ) from exc
    return Yolo26PoseTrainingImports(cv2=cv2, np=np, torch=torch)


def resolve_yolo26_pose_training_device(
    *,
    torch_module: Any,
    extra_options: dict[str, object] | None,
) -> str:
    """根据训练参数解析 YOLO26 pose 训练设备。"""

    return resolve_single_training_device_name(
        torch_module=torch_module,
        extra_options=extra_options,
    )


def build_yolo26_pose_autocast_context(
    *,
    torch_module: Any,
    precision: str,
    device_name: str,
) -> Any:
    """构建 YOLO26 pose 训练使用的 autocast context。"""

    if precision == "fp16" and "cuda" in device_name:
        return torch_module.amp.autocast("cuda")
    return nullcontext()


__all__ = [
    "Yolo26PoseTrainingImports",
    "build_yolo26_pose_autocast_context",
    "require_yolo26_pose_training_imports",
    "resolve_yolo26_pose_training_device",
]
