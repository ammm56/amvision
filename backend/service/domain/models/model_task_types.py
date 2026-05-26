"""模型任务分类定义。"""

from __future__ import annotations

from typing import Final, Literal


ModelTaskType = Literal[
    "detection",
    "segmentation",
    "pose",
    "obb",
    "classification",
    "multimodal-vl",
]


DETECTION_TASK_TYPE: Final[ModelTaskType] = "detection"
SEGMENTATION_TASK_TYPE: Final[ModelTaskType] = "segmentation"
POSE_TASK_TYPE: Final[ModelTaskType] = "pose"
OBB_TASK_TYPE: Final[ModelTaskType] = "obb"
CLASSIFICATION_TASK_TYPE: Final[ModelTaskType] = "classification"
MULTIMODAL_VL_TASK_TYPE: Final[ModelTaskType] = "multimodal-vl"

SUPPORTED_MODEL_TASK_TYPES: Final[tuple[ModelTaskType, ...]] = (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    POSE_TASK_TYPE,
    OBB_TASK_TYPE,
    CLASSIFICATION_TASK_TYPE,
    MULTIMODAL_VL_TASK_TYPE,
)


def is_model_task_type(value: str) -> bool:
    """判断给定字符串是否属于当前已登记的模型任务分类。"""

    return value in SUPPORTED_MODEL_TASK_TYPES
