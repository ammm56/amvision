"""YOLO11 core 任务配置入口。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo11_core.cfg.classification import (
    YOLO11_CLASSIFICATION_MODEL_CONFIG,
)
from backend.service.application.models.yolo11_core.cfg.detection import (
    YOLO11_DETECTION_MODEL_CONFIG,
)
from backend.service.application.models.yolo11_core.cfg.obb import (
    YOLO11_OBB_MODEL_CONFIG,
)
from backend.service.application.models.yolo11_core.cfg.pose import (
    YOLO11_POSE_MODEL_CONFIG,
)
from backend.service.application.models.yolo11_core.cfg.segmentation import (
    YOLO11_SEGMENTATION_MODEL_CONFIG,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YOLO11_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    DETECTION_TASK_TYPE: YOLO11_DETECTION_MODEL_CONFIG,
    SEGMENTATION_TASK_TYPE: YOLO11_SEGMENTATION_MODEL_CONFIG,
    POSE_TASK_TYPE: YOLO11_POSE_MODEL_CONFIG,
    OBB_TASK_TYPE: YOLO11_OBB_MODEL_CONFIG,
    CLASSIFICATION_TASK_TYPE: YOLO11_CLASSIFICATION_MODEL_CONFIG,
}


def get_yolo11_model_config(*, task_type: str) -> dict[str, object]:
    """读取 YOLO11 指定任务分类的模型配置副本。"""

    model_config = YOLO11_MODEL_CONFIGS.get(task_type)
    if model_config is None:
        raise InvalidRequestError(
            "YOLO11 尚未接通指定任务分类",
            details={"model_type": "yolo11", "task_type": task_type},
        )
    return deepcopy(model_config)


__all__ = [
    "YOLO11_CLASSIFICATION_MODEL_CONFIG",
    "YOLO11_DETECTION_MODEL_CONFIG",
    "YOLO11_MODEL_CONFIGS",
    "YOLO11_OBB_MODEL_CONFIG",
    "YOLO11_POSE_MODEL_CONFIG",
    "YOLO11_SEGMENTATION_MODEL_CONFIG",
    "get_yolo11_model_config",
]
