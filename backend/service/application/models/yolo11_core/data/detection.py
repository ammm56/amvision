"""YOLO11 detection 训练和评估 batch 编码。"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)
from backend.service.application.models.yolo11_core.data.augmentation import (
    Yolo11TaskAugmentationOptions,
    apply_yolo11_random_affine,
    apply_yolo11_random_hsv,
    blend_yolo11_mixup_images,
    flip_yolo11_image_horizontally,
    resize_yolo11_image_to_canvas,
    should_apply_yolo11_horizontal_flip,
    transform_yolo11_boxes_xyxy,
)
from backend.service.application.models.yolo_core_common.data.mosaic import (
    YoloDetectionMosaicItem,
    build_yolo_detection_mosaic4,
)
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
    letterbox_yolo_image,
    scale_yolo_box_to_letterbox,
)


@dataclass(frozen=True)
class Yolo11DetectionResolvedSplit:
    """描述一个已经解析完成的 YOLO11 detection DatasetExport split。"""

    name: str
    image_root: Path
    sample_count: int
    annotation_payload: dict[str, object]
    annotation_file: Path | None = None


@dataclass(frozen=True)
class Yolo11DetectionTrainingAnnotation:
    """描述 YOLO11 detection 单个训练目标的原图 bbox 与类别。"""

    category_index: int
    category_id: int
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class Yolo11DetectionTrainingSample:
    """描述 YOLO11 detection 一张训练图片和完整检测标注。"""

    image_id: int
    image_path: Path
    image_width: int
    image_height: int
    annotations: tuple[Yolo11DetectionTrainingAnnotation, ...]


@dataclass(frozen=True)
class Yolo11DetectionPreparedTarget:
    """描述 YOLO11 detection 单张图片在当前输入尺寸下的训练目标。"""

    image_id: int
    image_width: int
    image_height: int
    boxes_xyxy: tuple[tuple[float, float, float, float], ...]
    category_indexes: tuple[int, ...]
    letterbox_transform: YoloLetterboxTransform | None = None


def build_yolo11_detection_training_batch(
    *,
    imports: Any,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    device: str,
    runtime_precision: str,
    augment_training: bool = False,
    available_samples: Sequence[Any] | None = None,
    augmentation_options: Yolo11TaskAugmentationOptions | None = None,
) -> tuple[Any, tuple[Yolo11DetectionPreparedTarget, ...]]:
    """把 YOLO11 detection 样本拼成训练或 validation batch。"""

    image_tensors: list[Any] = []
    prepared_targets: list[Yolo11DetectionPreparedTarget] = []
    resolved_available_samples = tuple(available_samples or samples)
    effective_options = (
        augmentation_options or _build_disabled_yolo11_detection_augmentation()
    )
    for sample in samples:
        letterbox_transform = None
        if augment_training:
            prepared_image, resized_boxes, resized_categories = (
                _prepare_yolo11_detection_sample_with_augmentation(
                    imports=imports,
                    primary_sample=sample,
                    available_samples=resolved_available_samples,
                    input_size=input_size,
                    augmentation_options=effective_options,
                )
            )
        else:
            (
                prepared_image,
                resized_boxes,
                resized_categories,
                letterbox_transform,
            ) = (
                _prepare_yolo11_detection_sample_without_augmentation(
                    imports=imports,
                    sample=sample,
                    input_size=input_size,
                )
            )
        rgb_image = imports.cv2.cvtColor(prepared_image, imports.cv2.COLOR_BGR2RGB)
        image_array = rgb_image.astype(imports.np.float32) / 255.0
        image_array = imports.np.transpose(image_array, (2, 0, 1))
        image_tensors.append(imports.torch.from_numpy(image_array))
        prepared_targets.append(
            Yolo11DetectionPreparedTarget(
                image_id=int(sample.image_id),
                image_width=int(
                    input_size[1] if augment_training else sample.image_width
                ),
                image_height=int(
                    input_size[0] if augment_training else sample.image_height
                ),
                boxes_xyxy=tuple(resized_boxes),
                category_indexes=tuple(resized_categories),
                letterbox_transform=letterbox_transform,
            )
        )

    images = move_yolo_tensor_to_training_device(
        imports.torch.stack(image_tensors, dim=0),
        device=device,
        runtime_precision=runtime_precision,
    )
    return images, tuple(prepared_targets)


def serialize_yolo11_detection_augmentation_options(
    augmentation_options: Yolo11TaskAugmentationOptions | None,
) -> dict[str, object]:
    """把 YOLO11 detection 增强参数转成训练摘要可记录的普通 dict。"""

    if augmentation_options is None:
        augmentation_options = _build_disabled_yolo11_detection_augmentation()
    return {
        "hsv_prob": float(augmentation_options.hsv_prob),
        "flip_prob": float(augmentation_options.flip_prob),
        "mosaic_prob": float(augmentation_options.mosaic_prob),
        "mixup_prob": float(augmentation_options.mixup_prob),
        "enable_mixup": bool(augmentation_options.enable_mixup),
        "affine_prob": float(augmentation_options.affine_prob),
        "degrees": float(augmentation_options.degrees),
        "translate": float(augmentation_options.translate),
        "scale": float(augmentation_options.scale),
        "shear": float(augmentation_options.shear),
        "perspective": float(augmentation_options.perspective),
        "mosaic_scale": tuple(
            float(value) for value in augmentation_options.mosaic_scale
        ),
        "mixup_scale": tuple(
            float(value) for value in augmentation_options.mixup_scale
        ),
        "close_mosaic_epochs": int(augmentation_options.close_mosaic_epochs),
        "multi_scale": bool(augmentation_options.multi_scale),
        "multi_scale_range": tuple(
            float(value) for value in augmentation_options.multi_scale_range
        ),
        "multi_scale_stride": int(augmentation_options.multi_scale_stride),
    }


def _prepare_yolo11_detection_sample_without_augmentation(
    *,
    imports: Any,
    sample: Any,
    input_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int], YoloLetterboxTransform]:
    """按 YOLO LetterBox 规则准备单张 YOLO11 detection 样本。"""

    image = _load_yolo11_detection_image(imports=imports, sample=sample)
    return _letterbox_yolo11_detection_sample_to_size(
        imports=imports,
        image=image,
        annotations=tuple(sample.annotations),
        input_size=input_size,
    )


def _prepare_yolo11_detection_sample_with_augmentation(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    input_size: tuple[int, int],
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造启用增强后的 YOLO11 detection 训练样本。"""

    if (
        augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        image, boxes_xyxy, category_indexes = _build_yolo11_detection_mosaic_sample(
            imports=imports,
            primary_sample=primary_sample,
            available_samples=tuple(available_samples),
            input_size=input_size,
            augmentation_options=augmentation_options,
        )
    else:
        image, boxes_xyxy, category_indexes, _ = (
            _prepare_yolo11_detection_sample_without_augmentation(
                imports=imports,
                sample=primary_sample,
                input_size=input_size,
            )
        )

    if (
        augmentation_options.enable_mixup
        and augmentation_options.mixup_prob > 0.0
        and random.random() < augmentation_options.mixup_prob
    ):
        mixup_source_sample = random.choice(
            tuple(available_samples) or (primary_sample,)
        )
        if (
            augmentation_options.mosaic_prob > 0.0
            and random.random() < augmentation_options.mosaic_prob
        ):
            mixup_image, mixup_boxes, mixup_categories = (
                _build_yolo11_detection_mosaic_sample(
                    imports=imports,
                    primary_sample=mixup_source_sample,
                    available_samples=tuple(available_samples),
                    input_size=input_size,
                    augmentation_options=augmentation_options,
                )
            )
        else:
            mixup_image, mixup_boxes, mixup_categories = (
                _build_yolo11_detection_scaled_sample(
                    imports=imports,
                    sample=mixup_source_sample,
                    input_size=input_size,
                    scale_range=augmentation_options.mixup_scale,
                )
            )
        image = blend_yolo11_mixup_images(
            imports=imports,
            image=image,
            other_image=mixup_image,
        )
        boxes_xyxy.extend(mixup_boxes)
        category_indexes.extend(mixup_categories)

    image = apply_yolo11_random_hsv(
        imports=imports,
        image=image,
        hsv_prob=augmentation_options.hsv_prob,
    )
    image, boxes_xyxy = _apply_yolo11_detection_flip(
        image=image,
        boxes_xyxy=boxes_xyxy,
        flip_prob=augmentation_options.flip_prob,
        input_size=input_size,
    )
    image, boxes_xyxy, category_indexes = _apply_yolo11_detection_affine(
        imports=imports,
        image=image,
        boxes_xyxy=boxes_xyxy,
        category_indexes=category_indexes,
        input_size=input_size,
        augmentation_options=augmentation_options,
    )
    return _filter_yolo11_detection_boxes(
        boxes_xyxy=boxes_xyxy,
        category_indexes=category_indexes,
        input_size=input_size,
        image=image,
    )


def _build_yolo11_detection_mosaic_sample(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    input_size: tuple[int, int],
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造一张 Ultralytics 风格 YOLO11 detection Mosaic 样本。"""

    selected_samples = [primary_sample]
    selected_samples.extend(
        random.choice(tuple(available_samples) or (primary_sample,)) for _ in range(3)
    )
    items = tuple(
        _build_yolo11_detection_mosaic_item(
            imports=imports,
            sample=sample,
        )
        for sample in selected_samples
    )
    return build_yolo_detection_mosaic4(
        cv2_module=imports.cv2,
        np_module=imports.np,
        items=items,
        input_size=input_size,
    )


def _build_yolo11_detection_mosaic_item(
    *,
    imports: Any,
    sample: Any,
) -> YoloDetectionMosaicItem:
    """把 YOLO11 detection 样本转换为 Mosaic 输入对象。"""

    image = _load_yolo11_detection_image(imports=imports, sample=sample)
    return YoloDetectionMosaicItem(
        image=image,
        boxes_xyxy=tuple(
            tuple(float(value) for value in annotation.bbox_xyxy)
            for annotation in sample.annotations
        ),
        category_indexes=tuple(
            int(annotation.category_index) for annotation in sample.annotations
        ),
    )


def _build_yolo11_detection_scaled_sample(
    *,
    imports: Any,
    sample: Any,
    input_size: tuple[int, int],
    scale_range: tuple[float, float],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """构造 MixUp 使用的 YOLO11 detection 缩放样本。"""

    return _build_yolo11_detection_scaled_cell(
        imports=imports,
        sample=sample,
        output_size=input_size,
        scale_gain=random.uniform(*scale_range),
    )


def _build_yolo11_detection_scaled_cell(
    *,
    imports: Any,
    sample: Any,
    output_size: tuple[int, int],
    scale_gain: float,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """把样本按随机缩放后裁剪或填充到指定画布尺寸。"""

    image = _load_yolo11_detection_image(imports=imports, sample=sample)
    output_height, output_width = int(output_size[0]), int(output_size[1])
    canvas, resize_scale, pad_xy = resize_yolo11_image_to_canvas(
        imports=imports,
        image=image,
        output_size=(output_width, output_height),
        scale_gain=scale_gain,
    )
    boxes_xyxy: list[tuple[float, float, float, float]] = []
    category_indexes: list[int] = []
    for annotation in sample.annotations:
        clipped_box = _clip_yolo11_detection_box(
            box_xyxy=(
                float(annotation.bbox_xyxy[0]) * resize_scale + float(pad_xy[0]),
                float(annotation.bbox_xyxy[1]) * resize_scale + float(pad_xy[1]),
                float(annotation.bbox_xyxy[2]) * resize_scale + float(pad_xy[0]),
                float(annotation.bbox_xyxy[3]) * resize_scale + float(pad_xy[1]),
            ),
            input_size=output_size,
        )
        if clipped_box is None:
            continue
        boxes_xyxy.append(clipped_box)
        category_indexes.append(int(annotation.category_index))
    return canvas, boxes_xyxy, category_indexes


def _letterbox_yolo11_detection_sample_to_size(
    *,
    imports: Any,
    image: Any,
    annotations: tuple[Any, ...],
    input_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]], list[int], YoloLetterboxTransform]:
    """把单张 YOLO11 detection 样本按 LetterBox 映射到目标尺寸。"""

    letterboxed, transform = letterbox_yolo_image(
        cv2_module=imports.cv2,
        np_module=imports.np,
        image=image,
        input_size=input_size,
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
        category_indexes.append(int(annotation.category_index))
    return letterboxed, boxes_xyxy, category_indexes, transform


def _load_yolo11_detection_image(*, imports: Any, sample: Any) -> Any:
    """读取单张 YOLO11 detection 训练样本图片。"""

    image = imports.cv2.imread(str(sample.image_path), imports.cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取 YOLO11 detection 训练图片: {sample.image_path}")
    return image


def _apply_yolo11_detection_flip(
    *,
    image: Any,
    boxes_xyxy: list[tuple[float, float, float, float]],
    flip_prob: float,
    input_size: tuple[int, int],
) -> tuple[Any, list[tuple[float, float, float, float]]]:
    """按概率执行 YOLO11 detection 水平翻转。"""

    if not should_apply_yolo11_horizontal_flip(flip_prob):
        return image, boxes_xyxy
    output_width = float(input_size[1])
    flipped_boxes: list[tuple[float, float, float, float]] = []
    for x1, y1, x2, y2 in boxes_xyxy:
        flipped_boxes.append((output_width - x2, y1, output_width - x1, y2))
    return flip_yolo11_image_horizontally(image), flipped_boxes


def _apply_yolo11_detection_affine(
    *,
    imports: Any,
    image: Any,
    boxes_xyxy: list[tuple[float, float, float, float]],
    category_indexes: list[int],
    input_size: tuple[int, int],
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """执行 YOLO11 detection random affine，并同步 bbox。"""

    output_height, output_width = int(input_size[0]), int(input_size[1])
    transformed_image, matrix, applied = apply_yolo11_random_affine(
        imports=imports,
        image=image,
        output_size=(output_width, output_height),
        augmentation_options=augmentation_options,
    )
    if not applied or matrix is None or not boxes_xyxy:
        return transformed_image, boxes_xyxy, category_indexes
    transformed_boxes, kept_indices = transform_yolo11_boxes_xyxy(
        imports=imports,
        boxes_xyxy=boxes_xyxy,
        matrix=matrix,
        output_size=(output_width, output_height),
        perspective=augmentation_options.perspective,
        area_threshold=0.1,
    )
    return (
        transformed_image,
        [tuple(float(value) for value in box) for box in transformed_boxes],
        [int(category_indexes[index]) for index in kept_indices],
    )


def _filter_yolo11_detection_boxes(
    *,
    boxes_xyxy: list[tuple[float, float, float, float]],
    category_indexes: list[int],
    input_size: tuple[int, int],
    image: Any,
) -> tuple[Any, list[tuple[float, float, float, float]], list[int]]:
    """过滤增强后退化或越界的 YOLO11 detection bbox。"""

    filtered_boxes: list[tuple[float, float, float, float]] = []
    filtered_categories: list[int] = []
    for box_xyxy, category_index in zip(boxes_xyxy, category_indexes, strict=False):
        clipped_box = _clip_yolo11_detection_box(
            box_xyxy=box_xyxy, input_size=input_size
        )
        if clipped_box is None:
            continue
        filtered_boxes.append(clipped_box)
        filtered_categories.append(int(category_index))
    return image, filtered_boxes, filtered_categories


def _clip_yolo11_detection_box(
    *,
    box_xyxy: tuple[float, float, float, float],
    input_size: tuple[int, int],
) -> tuple[float, float, float, float] | None:
    """把 YOLO11 detection bbox 裁剪到图像范围内。"""

    output_height, output_width = float(input_size[0]), float(input_size[1])
    x1 = max(0.0, min(float(box_xyxy[0]), output_width))
    y1 = max(0.0, min(float(box_xyxy[1]), output_height))
    x2 = max(0.0, min(float(box_xyxy[2]), output_width))
    y2 = max(0.0, min(float(box_xyxy[3]), output_height))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _build_disabled_yolo11_detection_augmentation() -> Yolo11TaskAugmentationOptions:
    """构造关闭增强的 YOLO11 detection 默认参数。"""

    return Yolo11TaskAugmentationOptions(
        hsv_prob=0.0,
        flip_prob=0.0,
        mosaic_prob=0.0,
        mixup_prob=0.0,
        enable_mixup=False,
        affine_prob=0.0,
        degrees=0.0,
        translate=0.0,
        scale=0.0,
        shear=0.0,
        perspective=0.0,
        mosaic_scale=(1.0, 1.0),
        mixup_scale=(1.0, 1.0),
        close_mosaic_epochs=0,
        multi_scale=False,
    )


__all__ = [
    "Yolo11DetectionPreparedTarget",
    "Yolo11DetectionResolvedSplit",
    "Yolo11DetectionTrainingAnnotation",
    "Yolo11DetectionTrainingSample",
    "build_yolo11_detection_training_batch",
    "serialize_yolo11_detection_augmentation_options",
]
