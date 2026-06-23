"""YOLO 主线模型统一分发入口。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo11_core import (
    YOLO11_MODEL_CONFIGS,
    build_yolo11_model,
)
from backend.service.application.models.yolo26_core import (
    YOLO26_MODEL_CONFIGS,
    build_yolo26_model,
)
from backend.service.application.models.yolov8_core import (
    YOLOV8_MODEL_CONFIGS,
    build_yolov8_model,
)


YOLO_MODEL_CONFIGS: dict[str, dict[str, dict[str, object]]] = {
    "yolov8": YOLOV8_MODEL_CONFIGS,
    "yolo11": YOLO11_MODEL_CONFIGS,
    "yolo26": YOLO26_MODEL_CONFIGS,
}


def get_yolo_model_config(*, model_type: str, task_type: str) -> dict[str, object]:
    """读取指定模型分类和任务分类对应的项目内模型配置。"""

    task_configs = YOLO_MODEL_CONFIGS.get(model_type)
    if task_configs is None:
        raise InvalidRequestError(
            "当前不支持指定的 YOLO 主线模型分类",
            details={"model_type": model_type},
        )
    model_config = task_configs.get(task_type)
    if model_config is None:
        raise InvalidRequestError(
            "当前 YOLO 主线模型分类尚未接通指定任务分类",
            details={"model_type": model_type, "task_type": task_type},
        )
    return deepcopy(model_config)


def build_yolo_model(
    *,
    model_type: str,
    task_type: str,
    model_scale: str,
    num_classes: int,
    model_config_overrides: dict[str, object] | None = None,
) -> Any:
    """按模型分类和任务分类分发到对应 YOLO core builder。"""

    builders = {
        "yolov8": build_yolov8_model,
        "yolo11": build_yolo11_model,
        "yolo26": build_yolo26_model,
    }
    builder = builders.get(model_type)
    if builder is None:
        raise InvalidRequestError(
            "当前不支持指定的 YOLO 主线模型分类",
            details={"model_type": model_type},
        )
    return builder(
        task_type=task_type,
        model_scale=model_scale,
        num_classes=num_classes,
        model_config_overrides=deepcopy(model_config_overrides),
    )
