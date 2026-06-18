"""YOLOv8 core 任务配置入口。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_core.cfg.classification import (
    YOLOV8_CLASSIFICATION_MODEL_CONFIG,
)
from backend.service.application.models.yolov8_core.cfg.detection import (
    YOLOV8_DETECTION_MODEL_CONFIG,
)
from backend.service.application.models.yolov8_core.cfg.obb import (
    YOLOV8_OBB_MODEL_CONFIG,
)
from backend.service.application.models.yolov8_core.cfg.pose import (
    YOLOV8_POSE_MODEL_CONFIG,
)
from backend.service.application.models.yolov8_core.cfg.segmentation import (
    YOLOV8_SEGMENTATION_MODEL_CONFIG,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YOLOV8_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    DETECTION_TASK_TYPE: YOLOV8_DETECTION_MODEL_CONFIG,
    SEGMENTATION_TASK_TYPE: YOLOV8_SEGMENTATION_MODEL_CONFIG,
    POSE_TASK_TYPE: YOLOV8_POSE_MODEL_CONFIG,
    OBB_TASK_TYPE: YOLOV8_OBB_MODEL_CONFIG,
    CLASSIFICATION_TASK_TYPE: YOLOV8_CLASSIFICATION_MODEL_CONFIG,
}


def get_yolov8_model_config(*, task_type: str) -> dict[str, object]:
    """读取 YOLOv8 指定任务分类的模型配置副本。"""

    model_config = YOLOV8_MODEL_CONFIGS.get(task_type)
    if model_config is None:
        raise InvalidRequestError(
            "YOLOv8 尚未接通指定任务分类",
            details={"model_type": "yolov8", "task_type": task_type},
        )
    return deepcopy(model_config)


__all__ = [
    "YOLOV8_CLASSIFICATION_MODEL_CONFIG",
    "YOLOV8_DETECTION_MODEL_CONFIG",
    "YOLOV8_MODEL_CONFIGS",
    "YOLOV8_OBB_MODEL_CONFIG",
    "YOLOV8_POSE_MODEL_CONFIG",
    "YOLOV8_SEGMENTATION_MODEL_CONFIG",
    "get_yolov8_model_config",
]
