"""平台模型支持矩阵。"""

from __future__ import annotations

from typing import Final

from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.domain.models.rfdetr_model_spec import RFDETR_SUPPORTED_TASKS
from backend.service.domain.models.yolo_model_profiles import YOLO_MODEL_PROFILES
from backend.service.domain.models.yolox_model_spec import DEFAULT_YOLOX_MODEL_SPEC


RFDETR_MODEL_TYPE: Final[str] = "rfdetr"

SUPPORTED_PLATFORM_TASK_TYPES: Final[tuple[str, ...]] = (
    DETECTION_TASK_TYPE,
    CLASSIFICATION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    POSE_TASK_TYPE,
    OBB_TASK_TYPE,
)

SUPPORTED_PLATFORM_MODEL_TYPES: Final[tuple[str, ...]] = (
    DEFAULT_YOLOX_MODEL_SPEC.model_name,
    *tuple(YOLO_MODEL_PROFILES.keys()),
    RFDETR_MODEL_TYPE,
)


def _build_supported_task_types_by_model_type() -> dict[str, tuple[str, ...]]:
    """按 model_type 汇总平台支持的 task_type。"""

    mapping: dict[str, tuple[str, ...]] = {
        DEFAULT_YOLOX_MODEL_SPEC.model_name: tuple(DEFAULT_YOLOX_MODEL_SPEC.supported_tasks),
        RFDETR_MODEL_TYPE: tuple(RFDETR_SUPPORTED_TASKS),
    }
    for model_type, profile in YOLO_MODEL_PROFILES.items():
        mapping[model_type] = tuple(profile.supported_tasks)
    return mapping


SUPPORTED_PLATFORM_TASK_TYPES_BY_MODEL_TYPE: Final[dict[str, tuple[str, ...]]] = (
    _build_supported_task_types_by_model_type()
)


def _build_supported_model_types_by_task_type() -> dict[str, tuple[str, ...]]:
    """按 task_type 汇总平台支持的 model_type。"""

    mapping: dict[str, tuple[str, ...]] = {}
    for task_type in SUPPORTED_PLATFORM_TASK_TYPES:
        mapping[task_type] = tuple(
            model_type
            for model_type in SUPPORTED_PLATFORM_MODEL_TYPES
            if task_type in SUPPORTED_PLATFORM_TASK_TYPES_BY_MODEL_TYPE.get(model_type, ())
        )
    return mapping


SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE: Final[dict[str, tuple[str, ...]]] = (
    _build_supported_model_types_by_task_type()
)


def normalize_platform_model_type(model_type: str | None) -> str | None:
    """规范化 model_type 字符串。"""

    if isinstance(model_type, str) and model_type.strip():
        return model_type.strip().lower()
    return None


def is_supported_platform_model_type(task_type: str, model_type: str | None) -> bool:
    """判断给定 model_type 是否受指定 task_type 支持。"""

    normalized_model_type = normalize_platform_model_type(model_type)
    if normalized_model_type is None:
        return False
    return normalized_model_type in SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE.get(task_type, ())


def get_supported_platform_model_types(task_type: str | None = None) -> tuple[str, ...]:
    """返回指定 task_type 支持的 model_type 列表。"""

    if task_type is None:
        return SUPPORTED_PLATFORM_MODEL_TYPES
    return SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE.get(task_type, ())


def format_supported_platform_model_types(task_type: str | None = None) -> str:
    """返回适合说明文本使用的 model_type 列表字符串。"""

    return "、".join(get_supported_platform_model_types(task_type))


def build_platform_model_type_field_description(
    task_type: str | None = None,
    *,
    prefix: str = "模型分类；当前支持 ",
) -> str:
    """生成统一的 model_type 字段说明。"""

    return f"{prefix}{format_supported_platform_model_types(task_type)}"
