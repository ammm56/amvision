"""YOLOv8 detection 训练增强和样本缩放。"""

from __future__ import annotations

import random
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_core.data.augmentation import (
    apply_yolov8_random_affine,
    transform_yolov8_boxes_xyxy,
)
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
    letterbox_yolo_image,
    scale_yolo_box_to_letterbox,
)
from backend.service.application.models.yolov8_core.data.detection_types import (
    YoloV8DetectionAugmentationOptions,
    YoloV8DetectionTrainingAnnotation,
    YoloV8DetectionTrainingSample,
)


def prepare_yolov8_detection_sample_without_augmentation(
    *,
    imports: Any,
    sample: YoloV8DetectionTrainingSample,
    input_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int], YoloLetterboxTransform]:
    """按 YOLO LetterBox 规则准备单张 YOLOv8 detection 样本。"""

    image = _load_training_image_array(imports=imports, sample=sample)
    return _letterbox_detection_sample_to_size(
        imports=imports,
        image=image,
        annotations=sample.annotations,
        output_size=input_size,
    )


def prepare_yolov8_detection_sample_with_augmentation(
    *,
    imports: Any,
    primary_sample: YoloV8DetectionTrainingSample,
    available_samples: tuple[YoloV8DetectionTrainingSample, ...],
    input_size: tuple[int, int],
    augmentation_options: YoloV8DetectionAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造启用增强后的 YOLOv8 detection 训练样本。"""

    if augmentation_options.mosaic_prob > 0.0 and random.random() < augmentation_options.mosaic_prob:
        image, boxes_xyxy, category_indexes = _build_mosaic_detection_sample(
            imports=imports,
            primary_sample=primary_sample,
            available_samples=available_samples,
            input_size=input_size,
            augmentation_options=augmentation_options,
        )
    else:
        image, boxes_xyxy, category_indexes, _ = prepare_yolov8_detection_sample_without_augmentation(
            imports=imports,
            sample=primary_sample,
            input_size=input_size,
        )

    if (
        augmentation_options.enable_mixup
        and augmentation_options.mixup_prob > 0.0
        and random.random() < augmentation_options.mixup_prob
    ):
        mixup_source_sample = random.choice(available_samples)
        if augmentation_options.mosaic_prob > 0.0 and random.random() < augmentation_options.mosaic_prob:
            mixup_image, mixup_boxes, mixup_categories = _build_mosaic_detection_sample(
                imports=imports,
                primary_sample=mixup_source_sample,
                available_samples=available_samples,
                input_size=input_size,
                augmentation_options=augmentation_options,
            )
        else:
            mixup_image, mixup_boxes, mixup_categories = _build_scaled_mixup_sample(
                imports=imports,
                sample=mixup_source_sample,
                input_size=input_size,
                scale_range=augmentation_options.mixup_scale,
            )
        image = _apply_mixup(np_module=imports.np, image=image, other_image=mixup_image)
        boxes_xyxy.extend(mixup_boxes)
        category_indexes.extend(mixup_categories)

    image = _apply_random_hsv(
        imports=imports,
        image=image,
        hsv_prob=augmentation_options.hsv_prob,
    )
    image, boxes_xyxy = _apply_random_flip(
        image=image,
        boxes_xyxy=boxes_xyxy,
        flip_prob=augmentation_options.flip_prob,
        output_size=input_size,
    )
    image, boxes_xyxy, category_indexes = _apply_random_affine(
        imports=imports,
        image=image,
        boxes_xyxy=boxes_xyxy,
        category_indexes=category_indexes,
        output_size=input_size,
        augmentation_options=augmentation_options,
    )
    return _filter_training_boxes(
        boxes_xyxy=boxes_xyxy,
        category_indexes=category_indexes,
        output_size=input_size,
        image=image,
    )


def _build_mosaic_detection_sample(
    *,
    imports: Any,
    primary_sample: YoloV8DetectionTrainingSample,
    available_samples: tuple[YoloV8DetectionTrainingSample, ...],
    input_size: tuple[int, int],
    augmentation_options: YoloV8DetectionAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造一张 2x2 Mosaic YOLOv8 detection 样本。"""

    np_module = imports.np
    output_height, output_width = int(input_size[0]), int(input_size[1])
    top_height = output_height // 2
    left_width = output_width // 2
    placements = (
        (0, 0, top_height, left_width),
        (0, left_width, top_height, output_width - left_width),
        (top_height, 0, output_height - top_height, left_width),
        (top_height, left_width, output_height - top_height, output_width - left_width),
    )
    canvas = np_module.full((output_height, output_width, 3), 114, dtype=np_module.uint8)
    boxes_xyxy: list[tuple[float, float, float, float]] = []
    category_indexes: list[int] = []
    selected_samples = [primary_sample]
    selected_samples.extend(
        random.choice(available_samples) if available_samples else primary_sample
        for _ in range(3)
    )

    for sample, (top, left, cell_height, cell_width) in zip(selected_samples, placements, strict=True):
        scale_gain = random.uniform(
            augmentation_options.mosaic_scale[0],
            augmentation_options.mosaic_scale[1],
        )
        cell_image, cell_boxes, cell_categories = _build_scaled_cell_sample(
            imports=imports,
            sample=sample,
            output_size=(cell_height, cell_width),
            scale_gain=scale_gain,
        )
        canvas[top:top + cell_height, left:left + cell_width] = cell_image
        for box in cell_boxes:
            boxes_xyxy.append(
                (
                    float(box[0] + left),
                    float(box[1] + top),
                    float(box[2] + left),
                    float(box[3] + top),
                )
            )
        category_indexes.extend(cell_categories)
    return canvas, boxes_xyxy, category_indexes


def _build_scaled_mixup_sample(
    *,
    imports: Any,
    sample: YoloV8DetectionTrainingSample,
    input_size: tuple[int, int],
    scale_range: tuple[float, float],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造 MixUp 使用的缩放样本。"""

    scale_gain = random.uniform(scale_range[0], scale_range[1])
    return _build_scaled_cell_sample(
        imports=imports,
        sample=sample,
        output_size=input_size,
        scale_gain=scale_gain,
    )


def _build_scaled_cell_sample(
    *,
    imports: Any,
    sample: YoloV8DetectionTrainingSample,
    output_size: tuple[int, int],
    scale_gain: float,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """把样本按随机缩放后裁剪/填充到指定画布尺寸。"""

    np_module = imports.np
    image = _load_training_image_array(imports=imports, sample=sample)
    output_height, output_width = int(output_size[0]), int(output_size[1])
    source_height, source_width = int(image.shape[0]), int(image.shape[1])
    if source_height <= 0 or source_width <= 0:
        raise InvalidRequestError("YOLOv8 detection 训练样本图片尺寸不合法")
    base_scale = min(
        float(output_width) / max(1.0, float(source_width)),
        float(output_height) / max(1.0, float(source_height)),
    )
    resized_scale = max(1e-6, base_scale * max(0.01, float(scale_gain)))
    resized_width = max(1, int(round(source_width * resized_scale)))
    resized_height = max(1, int(round(source_height * resized_scale)))
    resized_image = imports.cv2.resize(
        image,
        (resized_width, resized_height),
        interpolation=imports.cv2.INTER_LINEAR,
    )
    canvas = np_module.full((output_height, output_width, 3), 114, dtype=np_module.uint8)

    if resized_width > output_width:
        source_x = random.randint(0, resized_width - output_width)
        target_x = 0
        copy_width = output_width
    else:
        source_x = 0
        target_x = random.randint(0, output_width - resized_width)
        copy_width = resized_width
    if resized_height > output_height:
        source_y = random.randint(0, resized_height - output_height)
        target_y = 0
        copy_height = output_height
    else:
        source_y = 0
        target_y = random.randint(0, output_height - resized_height)
        copy_height = resized_height
    canvas[target_y:target_y + copy_height, target_x:target_x + copy_width] = resized_image[
        source_y:source_y + copy_height,
        source_x:source_x + copy_width,
    ]

    boxes_xyxy: list[tuple[float, float, float, float]] = []
    category_indexes: list[int] = []
    for annotation in sample.annotations:
        scaled_x1 = float(annotation.bbox_xyxy[0]) * resized_scale - float(source_x) + float(target_x)
        scaled_y1 = float(annotation.bbox_xyxy[1]) * resized_scale - float(source_y) + float(target_y)
        scaled_x2 = float(annotation.bbox_xyxy[2]) * resized_scale - float(source_x) + float(target_x)
        scaled_y2 = float(annotation.bbox_xyxy[3]) * resized_scale - float(source_y) + float(target_y)
        clipped_box = _clip_box_xyxy(
            box_xyxy=(scaled_x1, scaled_y1, scaled_x2, scaled_y2),
            output_size=output_size,
        )
        if clipped_box is None:
            continue
        boxes_xyxy.append(clipped_box)
        category_indexes.append(annotation.category_index)
    return canvas, boxes_xyxy, category_indexes


def _letterbox_detection_sample_to_size(
    *,
    imports: Any,
    image: Any,
    annotations: tuple[YoloV8DetectionTrainingAnnotation, ...],
    output_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int], YoloLetterboxTransform]:
    """把单张 YOLOv8 detection 样本按 LetterBox 映射到目标尺寸。"""

    letterboxed, transform = letterbox_yolo_image(
        cv2_module=imports.cv2,
        np_module=imports.np,
        image=image,
        input_size=output_size,
    )
    boxes_xyxy: list[tuple[float, float, float, float]] = []
    category_indexes: list[int] = []
    for annotation in annotations:
        clipped_box = scale_yolo_box_to_letterbox(
            box_xyxy=annotation.bbox_xyxy,
            transform=transform,
        )
        if clipped_box is None:
            continue
        boxes_xyxy.append(clipped_box)
        category_indexes.append(annotation.category_index)
    return letterboxed, boxes_xyxy, category_indexes, transform


def _load_training_image_array(*, imports: Any, sample: YoloV8DetectionTrainingSample) -> Any:
    """读取单张 YOLOv8 detection 训练样本图片。"""

    image = imports.cv2.imread(str(sample.image_path), imports.cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidRequestError(
            "YOLOv8 detection 训练样本图片无法读取",
            details={"image_path": str(sample.image_path)},
        )
    return image


def _apply_mixup(*, np_module: Any, image: Any, other_image: Any) -> Any:
    """把两张同尺寸图片按固定权重混合。"""

    mixed = image.astype(np_module.float32) * 0.5 + other_image.astype(np_module.float32) * 0.5
    return mixed.clip(0.0, 255.0).astype(np_module.uint8)


def _apply_random_hsv(*, imports: Any, image: Any, hsv_prob: float) -> Any:
    """按概率执行随机 HSV 抖动。"""

    if hsv_prob <= 0.0 or random.random() >= hsv_prob:
        return image
    hsv_image = imports.cv2.cvtColor(image, imports.cv2.COLOR_BGR2HSV).astype(imports.np.float32)
    hue_gain = 1.0 + random.uniform(-0.015, 0.015)
    saturation_gain = 1.0 + random.uniform(-0.7, 0.7)
    value_gain = 1.0 + random.uniform(-0.4, 0.4)
    hsv_image[..., 0] = (hsv_image[..., 0] * hue_gain) % 180.0
    hsv_image[..., 1] = imports.np.clip(hsv_image[..., 1] * saturation_gain, 0.0, 255.0)
    hsv_image[..., 2] = imports.np.clip(hsv_image[..., 2] * value_gain, 0.0, 255.0)
    return imports.cv2.cvtColor(hsv_image.astype(imports.np.uint8), imports.cv2.COLOR_HSV2BGR)


def _apply_random_flip(
    *,
    image: Any,
    boxes_xyxy: list[tuple[float, float, float, float]],
    flip_prob: float,
    output_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]]]:
    """按概率执行随机水平翻转。"""

    if flip_prob <= 0.0 or random.random() >= flip_prob:
        return image, boxes_xyxy
    output_width = float(output_size[1])
    flipped_image = image[:, ::-1].copy()
    flipped_boxes: list[tuple[float, float, float, float]] = []
    for x1, y1, x2, y2 in boxes_xyxy:
        flipped_boxes.append((output_width - x2, y1, output_width - x1, y2))
    return flipped_image, flipped_boxes


def _apply_random_affine(
    *,
    imports: Any,
    image: Any,
    boxes_xyxy: list[tuple[float, float, float, float]],
    category_indexes: list[int],
    output_size: tuple[int, int],
    augmentation_options: YoloV8DetectionAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """执行 YOLOv8 random affine，并同步过滤 bbox 与类别索引。"""

    transformed_image, matrix, applied = apply_yolov8_random_affine(
        imports=imports,
        image=image,
        output_size=(int(output_size[1]), int(output_size[0])),
        augmentation_options=augmentation_options,
    )
    if not applied or matrix is None:
        return image, boxes_xyxy, category_indexes

    transformed_boxes, kept_indices = transform_yolov8_boxes_xyxy(
        imports=imports,
        boxes_xyxy=[list(box) for box in boxes_xyxy],
        matrix=matrix,
        output_size=(int(output_size[1]), int(output_size[0])),
        perspective=augmentation_options.perspective,
        area_threshold=0.01,
    )
    transformed_pairs: list[tuple[tuple[float, float, float, float], int]] = []
    for transformed_box, source_index in zip(transformed_boxes, kept_indices, strict=False):
        if source_index >= len(category_indexes):
            continue
        transformed_pairs.append(
            (
                tuple(float(value) for value in transformed_box),
                int(category_indexes[source_index]),
            )
        )
    return (
        transformed_image,
        [box for box, _ in transformed_pairs],
        [category_index for _, category_index in transformed_pairs],
    )


def _filter_training_boxes(
    *,
    boxes_xyxy: list[tuple[float, float, float, float]],
    category_indexes: list[int],
    output_size: tuple[int, int],
    image: Any,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """过滤增强后退化或越界的训练框。"""

    filtered_boxes: list[tuple[float, float, float, float]] = []
    filtered_categories: list[int] = []
    for box_xyxy, category_index in zip(boxes_xyxy, category_indexes, strict=False):
        clipped_box = _clip_box_xyxy(box_xyxy=box_xyxy, output_size=output_size)
        if clipped_box is None:
            continue
        filtered_boxes.append(clipped_box)
        filtered_categories.append(int(category_index))
    return image, filtered_boxes, filtered_categories


def _clip_box_xyxy(
    *,
    box_xyxy: tuple[float, float, float, float],
    output_size: tuple[int, int],
) -> tuple[float, float, float, float] | None:
    """把 bbox 裁剪到图像范围内。"""

    output_height, output_width = float(output_size[0]), float(output_size[1])
    x1 = max(0.0, min(float(box_xyxy[0]), output_width))
    y1 = max(0.0, min(float(box_xyxy[1]), output_height))
    x2 = max(0.0, min(float(box_xyxy[2]), output_width))
    y2 = max(0.0, min(float(box_xyxy[3]), output_height))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


__all__ = [
    "prepare_yolov8_detection_sample_with_augmentation",
    "prepare_yolov8_detection_sample_without_augmentation",
]
