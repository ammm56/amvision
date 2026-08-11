"""YOLOv8 classification loss。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.losses.classification import (
    compute_yolo_classification_loss,
    normalize_yolo_classification_training_outputs,
)


def normalize_yolov8_classification_training_outputs(
    *,
    outputs: object,
) -> tuple[Any, Any | None]:
    """把 YOLOv8 classification 训练输出规整为 logits 和 probabilities。"""

    return normalize_yolo_classification_training_outputs(
        outputs=outputs,
        family_name="YOLOv8",
    )


def compute_yolov8_classification_loss(
    *,
    torch_module: Any,
    outputs: object,
    targets: Any,
) -> tuple[Any, Any | None]:
    """计算 YOLOv8 classification 交叉熵损失。"""

    return compute_yolo_classification_loss(
        torch_module=torch_module,
        outputs=outputs,
        targets=targets,
        family_name="YOLOv8",
    )


__all__ = [
    "compute_yolov8_classification_loss",
    "normalize_yolov8_classification_training_outputs",
]
