"""三代 YOLO 共用的 COCO segmentation target 解析与栅格化。"""

from __future__ import annotations

from typing import Any

YOLO_SEGMENTATION_MASK_RATIO = 4


def downsample_yolo_segmentation_masks(
    masks: Any,
    *,
    mask_ratio: int = YOLO_SEGMENTATION_MASK_RATIO,
) -> Any:
    """按 Ultralytics 默认 mask_ratio 下采样实例 mask，降低 batch 内存。"""

    ratio = max(1, int(mask_ratio))
    if ratio == 1:
        return masks
    return masks[:, ::ratio, ::ratio].copy()


def select_yolo_object_segmentation(
    segmentations: Any,
    *,
    object_index: int,
    object_count: int,
) -> list[list[float]] | dict[str, object] | None:
    """按实例选择 polygon 或 COCO RLE，兼容单实例外层包装。"""

    if not isinstance(segmentations, list) or not segmentations:
        return None
    if object_count > 1:
        if object_index >= len(segmentations):
            return None
        value = segmentations[object_index]
    elif len(segmentations) == 1 and isinstance(segmentations[0], (list, dict)):
        value = segmentations[0]
    else:
        value = segmentations
    if isinstance(value, dict):
        return value
    return _normalize_polygon_group(value)


def rasterize_yolo_segmentation(
    *,
    cv2_module: Any,
    np_module: Any,
    segmentation: list[list[float]] | dict[str, object] | None,
    output_size: tuple[int, int],
    resize_scale: float,
    pad_xy: tuple[int, int],
) -> tuple[Any, bool]:
    """把原图坐标 polygon 或 COCO RLE 栅格化到目标画布。"""

    output_width, output_height = (int(output_size[0]), int(output_size[1]))
    mask = np_module.zeros((output_height, output_width), dtype=np_module.uint8)
    if isinstance(segmentation, dict):
        source_mask = decode_coco_rle_mask(
            segmentation=segmentation,
            np_module=np_module,
        )
        if source_mask is None:
            return mask, False
        resized_width = max(1, int(round(source_mask.shape[1] * float(resize_scale))))
        resized_height = max(1, int(round(source_mask.shape[0] * float(resize_scale))))
        resized_mask = cv2_module.resize(
            source_mask,
            (resized_width, resized_height),
            interpolation=cv2_module.INTER_NEAREST,
        )
        _paste_binary_mask(
            destination=mask,
            source=resized_mask,
            offset_xy=(int(pad_xy[0]), int(pad_xy[1])),
        )
        return mask, bool(np_module.any(mask))
    if not segmentation:
        return mask, False

    pad_x, pad_y = pad_xy
    valid = False
    for polygon in segmentation:
        if len(polygon) < 6 or len(polygon) % 2 != 0:
            continue
        points = np_module.asarray(polygon, dtype=np_module.float32).reshape(-1, 2)
        points[:, 0] = points[:, 0] * float(resize_scale) + float(pad_x)
        points[:, 1] = points[:, 1] * float(resize_scale) + float(pad_y)
        points[:, 0] = np_module.clip(points[:, 0], 0, output_width - 1)
        points[:, 1] = np_module.clip(points[:, 1], 0, output_height - 1)
        int_points = np_module.round(points).astype(np_module.int32)
        if int_points.shape[0] >= 3:
            cv2_module.fillPoly(mask, [int_points], 1)
            valid = True
    return mask, valid


def select_object_segmentation_polygons(
    segmentations: Any,
    *,
    object_index: int,
    object_count: int,
) -> list[list[float]] | dict[str, object] | None:
    """兼容旧入口，返回单实例 polygon 或 RLE。"""

    return select_yolo_object_segmentation(
        segmentations,
        object_index=object_index,
        object_count=object_count,
    )


def rasterize_segmentation_polygons(
    *,
    cv2_module: Any,
    np_module: Any,
    polygons: list[list[float]] | dict[str, object] | None,
    output_size: tuple[int, int],
    resize_scale: float,
    pad_xy: tuple[int, int],
) -> tuple[Any, bool]:
    """兼容旧入口，同时接受 COCO RLE。"""

    return rasterize_yolo_segmentation(
        cv2_module=cv2_module,
        np_module=np_module,
        segmentation=polygons,
        output_size=output_size,
        resize_scale=resize_scale,
        pad_xy=pad_xy,
    )


def decode_coco_rle_mask(*, segmentation: dict[str, object], np_module: Any) -> Any | None:
    """按 COCO Fortran 顺序惰性解码 compressed/uncompressed RLE。"""

    size = segmentation.get("size")
    counts = segmentation.get("counts")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or not all(isinstance(value, int) and value > 0 for value in size)
    ):
        return None
    if isinstance(counts, str):
        decoded_counts = _decode_compressed_coco_counts(counts)
    elif isinstance(counts, list) and all(
        isinstance(value, int) and value >= 0 for value in counts
    ):
        decoded_counts = [int(value) for value in counts]
    else:
        return None
    height, width = int(size[0]), int(size[1])
    if sum(decoded_counts) != height * width:
        return None
    flat = np_module.zeros((height * width,), dtype=np_module.uint8)
    offset = 0
    foreground = False
    for run_length in decoded_counts:
        next_offset = offset + int(run_length)
        if foreground:
            flat[offset:next_offset] = 1
        foreground = not foreground
        offset = next_offset
    return flat.reshape((height, width), order="F")


def _decode_compressed_coco_counts(value: str) -> list[int]:
    """解码 pycocotools 使用的 COCO compressed RLE counts 字符串。"""

    counts: list[int] = []
    position = 0
    while position < len(value):
        decoded = 0
        shift = 0
        more = True
        last_chunk = 0
        while more:
            if position >= len(value):
                return []
            last_chunk = ord(value[position]) - 48
            if last_chunk < 0:
                return []
            decoded |= (last_chunk & 0x1F) << (5 * shift)
            more = bool(last_chunk & 0x20)
            position += 1
            shift += 1
        if last_chunk & 0x10:
            decoded |= -1 << (5 * shift)
        if len(counts) > 2:
            decoded += counts[-2]
        if decoded < 0:
            return []
        counts.append(decoded)
    return counts


def _paste_binary_mask(*, destination: Any, source: Any, offset_xy: tuple[int, int]) -> None:
    """把可能越界的 source mask 裁剪后贴到 destination。"""

    offset_x, offset_y = offset_xy
    destination_height, destination_width = destination.shape[:2]
    source_height, source_width = source.shape[:2]
    destination_x1 = max(0, offset_x)
    destination_y1 = max(0, offset_y)
    destination_x2 = min(destination_width, offset_x + source_width)
    destination_y2 = min(destination_height, offset_y + source_height)
    if destination_x1 >= destination_x2 or destination_y1 >= destination_y2:
        return
    source_x1 = destination_x1 - offset_x
    source_y1 = destination_y1 - offset_y
    source_x2 = source_x1 + (destination_x2 - destination_x1)
    source_y2 = source_y1 + (destination_y2 - destination_y1)
    destination[destination_y1:destination_y2, destination_x1:destination_x2] = (
        source[source_y1:source_y2, source_x1:source_x2] > 0
    ).astype(destination.dtype)


def _normalize_polygon_group(value: Any) -> list[list[float]] | None:
    """把单实例 polygon 输入规整为 ``list[list[float]]``。"""

    if not isinstance(value, list) or not value:
        return None
    if all(isinstance(item, int | float) for item in value):
        polygon = [float(item) for item in value]
        return [polygon] if len(polygon) >= 6 and len(polygon) % 2 == 0 else None
    polygons: list[list[float]] = []
    for item in value:
        if not isinstance(item, list) or not all(
            isinstance(number, int | float) for number in item
        ):
            continue
        polygon = [float(number) for number in item]
        if len(polygon) >= 6 and len(polygon) % 2 == 0:
            polygons.append(polygon)
    return polygons or None


__all__ = [
    "YOLO_SEGMENTATION_MASK_RATIO",
    "decode_coco_rle_mask",
    "downsample_yolo_segmentation_masks",
    "rasterize_segmentation_polygons",
    "rasterize_yolo_segmentation",
    "select_object_segmentation_polygons",
    "select_yolo_object_segmentation",
]
