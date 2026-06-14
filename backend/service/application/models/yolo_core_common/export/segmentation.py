"""YOLO segmentation export 边界。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import ServiceConfigurationError


SEGMENTATION_EXPORT_OUTPUT_NAMES = ("predictions", "proto")


def resolve_segmentation_export_output_names() -> tuple[str, str]:
    """返回 segmentation 导出固定输出名。"""

    return SEGMENTATION_EXPORT_OUTPUT_NAMES


def normalize_segmentation_export_outputs(
    *,
    outputs: list[Any] | tuple[Any, ...],
) -> tuple[Any, Any]:
    """校验并返回 segmentation export forward 的 prediction/proto 双输出。"""

    if len(outputs) < 2:
        raise ServiceConfigurationError(
            "segmentation export forward 缺少 prediction/proto 双输出",
            details={"output_count": len(outputs)},
        )
    return outputs[0], outputs[1]
