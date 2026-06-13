"""YOLO26 core 任务配置。"""

from __future__ import annotations

from copy import deepcopy

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_config_utils import clone_detection_variant
from backend.service.application.models.yolo_primary_detection_model import (
    YOLO26_DETECTION_MODEL_CONFIG,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YOLO26_CLASSIFICATION_MODEL_CONFIG: dict[str, object] = {
    "scales": {
        "nano": (0.50, 0.25, 1024),
        "s": (0.50, 0.50, 1024),
        "m": (0.50, 1.00, 512),
        "l": (1.00, 1.00, 512),
        "x": (1.00, 1.50, 512),
    },
    "backbone": [
        (-1, 1, "Conv", (64, 3, 2)),
        (-1, 1, "Conv", (128, 3, 2)),
        (-1, 2, "C3k2", (256, False, 0.25)),
        (-1, 1, "Conv", (256, 3, 2)),
        (-1, 2, "C3k2", (512, False, 0.25)),
        (-1, 1, "Conv", (512, 3, 2)),
        (-1, 2, "C3k2", (512, True)),
        (-1, 1, "Conv", (1024, 3, 2)),
        (-1, 2, "C3k2", (1024, True)),
        (-1, 2, "C2PSA", (1024,)),
    ],
    "head": [
        (-1, 1, "Classify", ("nc",)),
    ],
}

YOLO26_MODEL_CONFIGS: dict[str, dict[str, object]] = {
    DETECTION_TASK_TYPE: deepcopy(YOLO26_DETECTION_MODEL_CONFIG),
    SEGMENTATION_TASK_TYPE: clone_detection_variant(
        YOLO26_DETECTION_MODEL_CONFIG,
        head_module_name="Segment26",
        head_args=("nc", 32, 256),
    ),
    POSE_TASK_TYPE: clone_detection_variant(
        YOLO26_DETECTION_MODEL_CONFIG,
        head_module_name="Pose26",
        head_args=("nc", "kpt_shape"),
        top_level_overrides={"kpt_shape": (17, 3)},
    ),
    OBB_TASK_TYPE: clone_detection_variant(
        YOLO26_DETECTION_MODEL_CONFIG,
        head_module_name="OBB26",
        head_args=("nc", 1),
    ),
    CLASSIFICATION_TASK_TYPE: deepcopy(YOLO26_CLASSIFICATION_MODEL_CONFIG),
}


def get_yolo26_model_config(*, task_type: str) -> dict[str, object]:
    """读取 YOLO26 指定任务的项目内模型配置。"""

    model_config = YOLO26_MODEL_CONFIGS.get(task_type)
    if model_config is None:
        raise InvalidRequestError(
            "YOLO26 尚未接通指定任务分类",
            details={"model_type": "yolo26", "task_type": task_type},
        )
    return deepcopy(model_config)
