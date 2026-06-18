"""YOLOv8 segmentation export 边界。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import ServiceConfigurationError


def resolve_yolov8_segmentation_export_output_names() -> tuple[str, str]:
    """返回 YOLOv8 segmentation 导出输出名。"""

    return ("predictions", "proto")


def normalize_yolov8_segmentation_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any, Any]:
    """校验并返回 YOLOv8 segmentation export 输出。"""

    if not isinstance(outputs, list | tuple) or len(outputs) < 2:
        raise ServiceConfigurationError(
            "YOLOv8 segmentation export forward 缺少 prediction/proto 双输出",
            details={"output_count": len(outputs) if isinstance(outputs, list | tuple) else 0},
        )
    return outputs[0], outputs[1]


__all__ = [
    "normalize_yolov8_segmentation_export_outputs",
    "resolve_yolov8_segmentation_export_output_names",
]
