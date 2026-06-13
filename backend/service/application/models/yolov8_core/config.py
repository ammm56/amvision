"""YOLOv8 core 任务配置。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_config_utils import clone_detection_variant
from backend.service.application.models.yolo_primary_detection_model import (
    YOLOV8_DETECTION_MODEL_CONFIG,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YOLOV8_CLASSIFICATION_MODEL_CONFIG: dict[str, object] = {
    "scales": {
        "nano": (0.33, 0.25, 1024),
        "s": (0.33, 0.50, 1024),
        "m": (0.67, 0.75, 1024),
        "l": (1.00, 1.00, 1024),
        "x": (1.00, 1.25, 1024),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 3, "C2f", (128, True)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 6, "C2f", (256, True)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 6, "C2f", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 3, "C2f", (1024, True)),
    ],
    "head": [
        (-1, 1, "Classify", ("nc",)),
    ],
}

YOLOV8_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    DETECTION_TASK_TYPE: deepcopy(YOLOV8_DETECTION_MODEL_CONFIG),
    SEGMENTATION_TASK_TYPE: clone_detection_variant(
        YOLOV8_DETECTION_MODEL_CONFIG,
        head_module_name="Segment",
        head_args=("nc", 32, 256),
    ),
    POSE_TASK_TYPE: clone_detection_variant(
        YOLOV8_DETECTION_MODEL_CONFIG,
        head_module_name="Pose",
        head_args=("nc", "kpt_shape"),
        top_level_overrides={"kpt_shape": (17, 3)},
    ),
    OBB_TASK_TYPE: clone_detection_variant(
        YOLOV8_DETECTION_MODEL_CONFIG,
        head_module_name="OBB",
        head_args=("nc", 1),
    ),
    CLASSIFICATION_TASK_TYPE: deepcopy(YOLOV8_CLASSIFICATION_MODEL_CONFIG),
}


def get_yolov8_model_config(*, task_type: str) -> dict[str, object]:
    """读取 YOLOv8 指定任务的项目内模型配置。"""

    model_config = YOLOV8_MODEL_CONFIGS.get(task_type)
    if model_config is None:
        raise InvalidRequestError(
            "YOLOv8 尚未接通指定任务分类",
            details={"model_type": "yolov8", "task_type": task_type},
        )
    return deepcopy(model_config)
