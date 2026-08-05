"""YOLO11 segmentation mask target 编码。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.targets.segmentation import (
    rasterize_yolo_segmentation,
    select_yolo_object_segmentation,
)


def select_yolo11_object_segmentation_polygons(
    segmentations: Any,
    *,
    object_index: int,
    object_count: int,
) -> list[list[float]] | dict[str, object] | None:
    """从 COCO 风格字段中取出单实例 polygon 或 RLE。"""

    return select_yolo_object_segmentation(
        segmentations,
        object_index=object_index,
        object_count=object_count,
    )


def rasterize_yolo11_segmentation_polygons(
    *,
    cv2_module: Any,
    np_module: Any,
    polygons: list[list[float]] | dict[str, object] | None,
    output_size: tuple[int, int],
    resize_scale: float,
    pad_xy: tuple[int, int],
) -> tuple[Any, bool]:
    """把原图 polygon 或 COCO RLE 栅格化到输入尺寸。"""

    return rasterize_yolo_segmentation(
        cv2_module=cv2_module,
        np_module=np_module,
        segmentation=polygons,
        output_size=output_size,
        resize_scale=resize_scale,
        pad_xy=pad_xy,
    )
