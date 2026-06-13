"""YOLOv8 core 模型构建入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_detection_model import build_yolo_detection_model
from backend.service.application.models.yolov8_core.config import get_yolov8_model_config
from backend.service.application.models.yolov8_core.heads import YOLOV8_HEAD_MODULES


def build_yolov8_model(
    *,
    task_type: str,
    model_scale: str,
    num_classes: int,
    model_config_overrides: dict[str, object] | None = None,
) -> Any:
    """按任务分类构建 YOLOv8 项目内模型。"""

    model_config = get_yolov8_model_config(task_type=task_type)
    if model_config_overrides:
        model_config.update(model_config_overrides)
    return build_yolo_detection_model(
        model_name=f"yolov8-{task_type}",
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
        head_module_map=YOLOV8_HEAD_MODULES,
    )
