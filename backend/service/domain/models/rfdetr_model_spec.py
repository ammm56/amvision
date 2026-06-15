"""RF-DETR 模型规格。"""

from __future__ import annotations

from typing import Final

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_DETECTION_DATASET_FORMAT,
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.service.domain.models.model_build_formats import (
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    ModelTaskType,
)

RFDETR_DETECTION_SCALES: Final[tuple[str, ...]] = ("nano", "s", "m", "l")
RFDETR_SEGMENTATION_SCALES: Final[tuple[str, ...]] = ("nano", "s", "m", "l", "x")
RFDETR_SUPPORTED_TASKS: Final[tuple[ModelTaskType, ...]] = (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
RFDETR_SUPPORTED_SCALES: Final[tuple[str, ...]] = (
    "nano",
    "s",
    "m",
    "l",
    "x",
)
RFDETR_SUPPORTED_BUILD_FORMATS: Final[tuple[str, ...]] = (
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
)
RFDETR_DETECTION_DATASET_FORMAT: Final[str] = COCO_DETECTION_DATASET_FORMAT
RFDETR_SEGMENTATION_DATASET_FORMAT: Final[str] = COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT
RFDETR_DEFAULT_DATASET_FORMAT: Final[str] = RFDETR_DETECTION_DATASET_FORMAT


def resolve_rfdetr_scales_for_task(task_type: ModelTaskType | str) -> tuple[str, ...]:
    """按任务类型返回 RF-DETR 公开支持的 scale。"""

    if task_type == DETECTION_TASK_TYPE:
        return RFDETR_DETECTION_SCALES
    if task_type == SEGMENTATION_TASK_TYPE:
        return RFDETR_SEGMENTATION_SCALES
    return ()


def resolve_rfdetr_default_dataset_format(task_type: ModelTaskType | str) -> str | None:
    """按任务类型返回 RF-DETR 训练默认使用的数据集导出格式。"""

    if task_type == DETECTION_TASK_TYPE:
        return RFDETR_DETECTION_DATASET_FORMAT
    if task_type == SEGMENTATION_TASK_TYPE:
        return RFDETR_SEGMENTATION_DATASET_FORMAT
    return None
