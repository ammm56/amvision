"""YOLOv8 segmentation export 边界。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.export import (
    normalize_segmentation_export_outputs,
    resolve_segmentation_export_output_names,
)


def resolve_yolov8_segmentation_export_output_names() -> tuple[str, str]:
    """返回 YOLOv8 segmentation 导出输出名。"""

    return resolve_segmentation_export_output_names()


def normalize_yolov8_segmentation_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any, Any]:
    """校验并返回 YOLOv8 segmentation export 输出。"""

    return normalize_segmentation_export_outputs(outputs=outputs)


__all__ = [
    "normalize_yolov8_segmentation_export_outputs",
    "resolve_yolov8_segmentation_export_output_names",
]
