"""workflow service node 共享平台常量。"""

from __future__ import annotations

from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.domain.models.platform_model_support import (
    SUPPORTED_PLATFORM_MODEL_TYPES,
)


WORKFLOW_SERVICE_TASK_TYPES: tuple[str, ...] = (
    DETECTION_TASK_TYPE,
    CLASSIFICATION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    POSE_TASK_TYPE,
    OBB_TASK_TYPE,
)
WORKFLOW_SERVICE_MODEL_TYPES: tuple[str, ...] = SUPPORTED_PLATFORM_MODEL_TYPES
WORKFLOW_SERVICE_MODEL_SCALES: tuple[str, ...] = (
    "nano",
    "tiny",
    "s",
    "m",
    "l",
    "x",
    "xx",
)

