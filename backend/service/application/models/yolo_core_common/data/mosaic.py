"""YOLO 主线 Mosaic 训练增强工具。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo_core_common.geometry import (
    clip_yolo_xyxy_box,
)


@dataclass(frozen=True)
class YoloDetectionMosaicItem:
    """描述一张参与 detection Mosaic 的原始图片和原图坐标标注。"""

    image: Any
    boxes_xyxy: tuple[tuple[float, float, float, float], ...]
    category_indexes: tuple[int, ...]


@dataclass(frozen=True)
class YoloMosaicImagePlacement:
    """描述单张图在 Mosaic 大画布中的真实缩放和偏移。"""

    index: int
    image: Any
    resize_scale: float
    offset_x: float
    offset_y: float
    canvas_width: int
    canvas_height: int


def build_yolo_detection_mosaic4(
    *,
    cv2_module: Any,
    np_module: Any,
    items: tuple[YoloDetectionMosaicItem, ...],
    input_size: tuple[int, int],
    fill_value: int = 114,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """按 Ultralytics Mosaic4 规则构造 detection 训练样本。

    输入尺寸使用 ``(height, width)``。每张图片先按长边保持比例缩到目标
    输入范围内，再放入 ``2H x 2W`` 大画布；随机 mosaic center 决定四张图
    的裁剪和摆放位置。后续 RandomPerspective 会负责从大画布裁回最终输入。
    """

    canvas, placements = build_yolo_mosaic4_canvas(
        cv2_module=cv2_module,
        np_module=np_module,
        images=tuple(item.image for item in items),
        input_size=input_size,
        fill_value=fill_value,
    )

    mosaic_boxes: list[tuple[float, float, float, float]] = []
    mosaic_categories: list[int] = []
    for placement in placements:
        item = items[placement.index]
        for box_xyxy, category_index in zip(
            item.boxes_xyxy,
            item.category_indexes,
            strict=False,
        ):
            clipped_box = clip_yolo_xyxy_box(
                box_xyxy=(
                    float(box_xyxy[0]) * placement.resize_scale + placement.offset_x,
                    float(box_xyxy[1]) * placement.resize_scale + placement.offset_y,
                    float(box_xyxy[2]) * placement.resize_scale + placement.offset_x,
                    float(box_xyxy[3]) * placement.resize_scale + placement.offset_y,
                ),
                image_width=placement.canvas_width,
                image_height=placement.canvas_height,
            )
            if clipped_box is None:
                continue
            mosaic_boxes.append(clipped_box)
            mosaic_categories.append(int(category_index))

    return canvas, mosaic_boxes, mosaic_categories


def build_yolo_mosaic4_canvas(
    *,
    cv2_module: Any,
    np_module: Any,
    images: tuple[Any, ...],
    input_size: tuple[int, int],
    fill_value: int = 114,
) -> tuple[Any, list[YoloMosaicImagePlacement]]:
    """按 Ultralytics Mosaic4 规则构造大画布并返回每张图的 placement。"""

    if not images:
        raise ValueError("Mosaic 至少需要一张训练图片")

    target_height = max(1, int(input_size[0]))
    target_width = max(1, int(input_size[1]))
    canvas_width = target_width * 2
    canvas_height = target_height * 2
    canvas = np_module.full(
        (canvas_height, canvas_width, 3),
        int(fill_value),
        dtype=np_module.uint8,
    )
    center_x = int(random.uniform(float(target_width) * 0.5, float(target_width) * 1.5))
    center_y = int(random.uniform(float(target_height) * 0.5, float(target_height) * 1.5))

    placements: list[YoloMosaicImagePlacement] = []
    for index, source_image in enumerate(images[:4]):
        resized_image, resize_scale = _resize_mosaic_image(
            cv2_module=cv2_module,
            image=source_image,
            input_size=(target_height, target_width),
        )
        image_height = int(resized_image.shape[0])
        image_width = int(resized_image.shape[1])
        dst, src = _resolve_mosaic4_copy_regions(
            index=index,
            center_x=center_x,
            center_y=center_y,
            image_width=image_width,
            image_height=image_height,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
        x1a, y1a, x2a, y2a = dst
        x1b, y1b, x2b, y2b = src
        if x2a <= x1a or y2a <= y1a or x2b <= x1b or y2b <= y1b:
            continue
        canvas[y1a:y2a, x1a:x2a] = resized_image[y1b:y2b, x1b:x2b]
        placements.append(
            YoloMosaicImagePlacement(
                index=index,
                image=resized_image,
                resize_scale=float(resize_scale),
                offset_x=float(x1a - x1b),
                offset_y=float(y1a - y1b),
                canvas_width=canvas_width,
                canvas_height=canvas_height,
            )
        )
    return canvas, placements


def _resize_mosaic_image(
    *,
    cv2_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """按长边保持比例缩放 Mosaic 单图，不做正方形填充。"""

    target_height = max(1, int(input_size[0]))
    target_width = max(1, int(input_size[1]))
    source_height = max(1, int(image.shape[0]))
    source_width = max(1, int(image.shape[1]))
    gain = min(
        float(target_height) / float(source_height),
        float(target_width) / float(source_width),
    )
    resized_width = max(1, min(target_width, int(round(source_width * gain))))
    resized_height = max(1, min(target_height, int(round(source_height * gain))))
    resized_image = cv2_module.resize(
        image,
        (resized_width, resized_height),
        interpolation=cv2_module.INTER_LINEAR,
    )
    return resized_image, float(gain)


def _resolve_mosaic4_copy_regions(
    *,
    index: int,
    center_x: int,
    center_y: int,
    image_width: int,
    image_height: int,
    canvas_width: int,
    canvas_height: int,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """按 Ultralytics Mosaic4 四象限规则计算目标和源图复制区域。"""

    if index == 0:
        dst = (
            max(center_x - image_width, 0),
            max(center_y - image_height, 0),
            center_x,
            center_y,
        )
        src = (
            image_width - (dst[2] - dst[0]),
            image_height - (dst[3] - dst[1]),
            image_width,
            image_height,
        )
    elif index == 1:
        dst = (
            center_x,
            max(center_y - image_height, 0),
            min(center_x + image_width, canvas_width),
            center_y,
        )
        src = (
            0,
            image_height - (dst[3] - dst[1]),
            min(image_width, dst[2] - dst[0]),
            image_height,
        )
    elif index == 2:
        dst = (
            max(center_x - image_width, 0),
            center_y,
            center_x,
            min(canvas_height, center_y + image_height),
        )
        src = (
            image_width - (dst[2] - dst[0]),
            0,
            image_width,
            min(dst[3] - dst[1], image_height),
        )
    else:
        dst = (
            center_x,
            center_y,
            min(center_x + image_width, canvas_width),
            min(center_y + image_height, canvas_height),
        )
        src = (
            0,
            0,
            min(image_width, dst[2] - dst[0]),
            min(image_height, dst[3] - dst[1]),
        )
    return dst, src


__all__ = [
    "YoloDetectionMosaicItem",
    "YoloMosaicImagePlacement",
    "build_yolo_detection_mosaic4",
    "build_yolo_mosaic4_canvas",
]
