"""YOLOv8 segmentation mask target 编码。"""

from __future__ import annotations

from typing import Any


def select_yolov8_object_segmentation_polygons(
    segmentations: Any,
    *,
    object_index: int,
    object_count: int,
) -> list[list[float]] | None:
    """从 COCO 风格 segmentation 字段中取出单个目标的 polygon 列表。"""

    if not isinstance(segmentations, list) or len(segmentations) == 0:
        return None
    if object_count == 1:
        return _normalize_yolov8_polygon_group(segmentations)
    if object_index >= len(segmentations):
        return None
    return _normalize_yolov8_polygon_group(segmentations[object_index])


def rasterize_yolov8_segmentation_polygons(
    *,
    cv2_module: Any,
    np_module: Any,
    polygons: list[list[float]] | None,
    output_size: tuple[int, int],
    resize_scale: float,
    pad_xy: tuple[int, int],
) -> tuple[Any, bool]:
    """把原图坐标 polygon 栅格化到 letterbox 后输入尺寸。"""

    output_width, output_height = output_size
    mask = np_module.zeros((int(output_height), int(output_width)), dtype=np_module.uint8)
    if not polygons:
        return mask, False

    pad_x, pad_y = pad_xy
    valid = False
    for polygon in polygons:
        if len(polygon) < 6 or len(polygon) % 2 != 0:
            continue
        points = np_module.asarray(polygon, dtype=np_module.float32).reshape(-1, 2)
        points[:, 0] = points[:, 0] * float(resize_scale) + float(pad_x)
        points[:, 1] = points[:, 1] * float(resize_scale) + float(pad_y)
        points[:, 0] = np_module.clip(points[:, 0], 0, int(output_width) - 1)
        points[:, 1] = np_module.clip(points[:, 1], 0, int(output_height) - 1)
        int_points = np_module.round(points).astype(np_module.int32)
        if int_points.shape[0] >= 3:
            cv2_module.fillPoly(mask, [int_points], 1)
            valid = True
    return mask, valid


def _normalize_yolov8_polygon_group(value: Any) -> list[list[float]] | None:
    """把单目标 polygon 输入规整成 ``list[list[float]]``。"""

    if not isinstance(value, list) or len(value) == 0:
        return None
    if all(isinstance(item, int | float) for item in value):
        polygon = [float(item) for item in value]
        return [polygon] if len(polygon) >= 6 and len(polygon) % 2 == 0 else None

    polygons: list[list[float]] = []
    for item in value:
        if not isinstance(item, list):
            continue
        if not all(isinstance(number, int | float) for number in item):
            continue
        polygon = [float(number) for number in item]
        if len(polygon) >= 6 and len(polygon) % 2 == 0:
            polygons.append(polygon)
    return polygons or None
