"""YOLO26 core 任务配置入口。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo26_core.cfg.classification import (
    YOLO26_CLASSIFICATION_MODEL_CONFIG,
)
from backend.service.application.models.yolo26_core.cfg.detection import (
    YOLO26_DETECTION_MODEL_CONFIG,
)
from backend.service.application.models.yolo26_core.cfg.obb import (
    YOLO26_OBB_MODEL_CONFIG,
)
from backend.service.application.models.yolo26_core.cfg.pose import (
    YOLO26_POSE_MODEL_CONFIG,
)
from backend.service.application.models.yolo26_core.cfg.segmentation import (
    YOLO26_SEGMENTATION_MODEL_CONFIG,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YOLO26_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    DETECTION_TASK_TYPE: YOLO26_DETECTION_MODEL_CONFIG,
    SEGMENTATION_TASK_TYPE: YOLO26_SEGMENTATION_MODEL_CONFIG,
    POSE_TASK_TYPE: YOLO26_POSE_MODEL_CONFIG,
    OBB_TASK_TYPE: YOLO26_OBB_MODEL_CONFIG,
    CLASSIFICATION_TASK_TYPE: YOLO26_CLASSIFICATION_MODEL_CONFIG,
}


def get_yolo26_model_config(*, task_type: str) -> dict[str, object]:
    """读取 YOLO26 指定任务分类的模型配置副本。"""

    model_config = YOLO26_MODEL_CONFIGS.get(task_type)
    if model_config is None:
        raise InvalidRequestError(
            "YOLO26 尚未接通指定任务分类",
            details={"model_type": "yolo26", "task_type": task_type},
        )
    return deepcopy(model_config)


__all__ = [
    "YOLO26_CLASSIFICATION_MODEL_CONFIG",
    "YOLO26_DETECTION_MODEL_CONFIG",
    "YOLO26_MODEL_CONFIGS",
    "YOLO26_OBB_MODEL_CONFIG",
    "YOLO26_POSE_MODEL_CONFIG",
    "YOLO26_SEGMENTATION_MODEL_CONFIG",
    "get_yolo26_model_config",
]
