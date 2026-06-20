"""YOLO11 core 模型构建入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo11_core.config import (
    get_yolo11_model_config,
)
from backend.service.application.models.yolo11_core.nn.model import (
    build_yolo11_graph_model,
)


def build_yolo11_model(
    *,
    task_type: str,
    model_scale: str,
    num_classes: int,
    model_config_overrides: dict[str, object] | None = None,
) -> Any:
    """按任务分类构建 YOLO11 项目内模型。"""

    model_config = get_yolo11_model_config(task_type=task_type)
    if model_config_overrides:
        model_config.update(model_config_overrides)
    return build_yolo11_graph_model(
        model_name=f"yolo11-{task_type}",
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
    )
