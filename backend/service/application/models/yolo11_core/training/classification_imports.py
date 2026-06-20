"""YOLO11 classification 训练依赖导入。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import ServiceConfigurationError


@dataclass(frozen=True)
class Yolo11ClassificationTrainingImports:
    """描述 YOLO11 classification 训练需要的本地模块。"""

    cv2: Any
    np: Any
    torch: Any


def require_yolo11_classification_training_imports() -> (
    Yolo11ClassificationTrainingImports
):
    """导入 YOLO11 classification 训练依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except ImportError as exc:
        raise ServiceConfigurationError(
            "YOLO11 classification 训练缺少必要依赖",
            details={"missing": str(exc)},
        ) from exc
    return Yolo11ClassificationTrainingImports(cv2=cv2, np=np, torch=torch)


__all__ = [
    "Yolo11ClassificationTrainingImports",
    "require_yolo11_classification_training_imports",
]
