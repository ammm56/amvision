"""YOLO26 core 模型构建入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_detection_model import build_yolo_detection_model
from backend.service.application.models.yolo26_core.config import get_yolo26_model_config
from backend.service.application.models.yolo26_core.heads import YOLO26_HEAD_MODULES


def build_yolo26_model(
    *,
    task_type: str,
    model_scale: str,
    num_classes: int,
    model_config_overrides: dict[str, object] | None = None,
) -> Any:
    """按任务分类构建 YOLO26 项目内模型。"""

    model_config = get_yolo26_model_config(task_type=task_type)
    if model_config_overrides:
        model_config.update(model_config_overrides)
    return build_yolo_detection_model(
        model_name=f"yolo26-{task_type}",
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
        head_module_map=YOLO26_HEAD_MODULES,
    )
