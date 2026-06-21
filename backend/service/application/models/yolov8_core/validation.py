"""YOLOv8 core 验收入口。"""

from __future__ import annotations

from torch import Tensor

from backend.service.application.models.validation.model_core_validation import (
    ModelCoreSnapshot,
    build_model_core_snapshot,
)
from backend.service.application.models.yolov8_core.model import build_yolov8_model


def build_yolov8_core_snapshot(
    *,
    task_type: str,
    model_scale: str,
    num_classes: int,
    example_input: Tensor | None = None,
) -> ModelCoreSnapshot:
    """构建 YOLOv8 模型并生成结构、参数和输出形状快照。"""

    model = build_yolov8_model(
        task_type=task_type,
        model_scale=model_scale,
        num_classes=num_classes,
    )
    return build_model_core_snapshot(
        model=model,
        model_type="yolov8",
        task_type=task_type,
        model_scale=model_scale,
        num_classes=num_classes,
        example_input=example_input,
    )
