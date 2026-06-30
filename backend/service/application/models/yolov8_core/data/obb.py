"""YOLOv8 OBB 训练和评估 batch 编码。"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo_core_common.data.mosaic import (
    build_yolo_mosaic4_canvas,
)
from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)
from backend.service.application.models.yolov8_core.data.augmentation import (
    YoloV8TaskAugmentationOptions,
    apply_yolov8_random_affine,
    apply_yolov8_random_hsv,
    blend_yolov8_mixup_images,
    flip_yolov8_image_horizontally,
    normalize_yolov8_obb_angle,
    resize_yolov8_image_to_canvas,
    select_yolov8_items_by_indices,
    should_apply_yolov8_horizontal_flip,
    transform_yolov8_obb_boxes,
)


@dataclass(frozen=True)
class YoloV8ObbPreparedTarget:
    """描述单张图的 YOLOv8 OBB 训练目标。"""

    boxes_xywhr: list[list[float]]
    category_indexes: list[int]


@dataclass(frozen=True)
class YoloV8ObbTrainingBatch:
    """描述 YOLOv8 OBB 训练或评估使用的 batch。"""

    images: Any
    targets: tuple[YoloV8ObbPreparedTarget, ...]


def build_yolov8_obb_training_batch(
    *,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
    augmentation_options: YoloV8TaskAugmentationOptions | None = None,
    available_samples: Sequence[Any] | None = None,
) -> YoloV8ObbTrainingBatch | None:
    """把样本列表编码为 YOLOv8 OBB 训练 batch。"""

    if not samples:
        return None

    target_width, target_height = input_size
    images: list[Any] = []
    targets: list[YoloV8ObbPreparedTarget] = []
    resolved_available_samples = tuple(available_samples or samples)
    for sample in samples:
        prepared = _prepare_yolov8_obb_sample_with_mix(
            imports=imports,
            primary_sample=sample,
            available_samples=resolved_available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
        if prepared is None:
            continue
        canvas, target = prepared
        canvas, target = _apply_yolov8_obb_augmentation(
            image=canvas,
            target=target,
            target_width=target_width,
            target_height=target_height,
            imports=imports,
            augmentation_options=augmentation_options,
        )

        tensor = canvas[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        images.append(imports.torch.from_numpy(tensor).float())
        targets.append(target)

    if not images:
        return None
    return YoloV8ObbTrainingBatch(
        images=move_yolo_tensor_to_training_device(
            imports.torch.stack(images, dim=0),
            device=device,
            runtime_precision=precision,
        ),
        targets=tuple(targets),
    )


def _prepare_yolov8_obb_sample_with_mix(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: YoloV8TaskAugmentationOptions | None,
) -> tuple[Any, YoloV8ObbPreparedTarget] | None:
    """构造可能包含 mosaic / mixup 的 OBB 样本。"""

    if (
        augmentation_options is not None
        and augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        prepared = _build_yolov8_obb_mosaic_sample(
            imports=imports,
            primary_sample=primary_sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    else:
        prepared = _prepare_yolov8_obb_single_sample(
            imports=imports,
            sample=primary_sample,
            output_size=(target_width, target_height),
            scale_gain=1.0,
        )
    if prepared is None:
        return None
    image, target = prepared
    if (
        augmentation_options is None
        or not augmentation_options.enable_mixup
        or augmentation_options.mixup_prob <= 0.0
        or random.random() >= augmentation_options.mixup_prob
    ):
        return image, target
    mixup_sample = random.choice(tuple(available_samples) or (primary_sample,))
    mixup_prepared = _prepare_yolov8_obb_mixup_sample(
        imports=imports,
        sample=mixup_sample,
        available_samples=available_samples,
        target_width=target_width,
        target_height=target_height,
        augmentation_options=augmentation_options,
    )
    if mixup_prepared is None:
        return image, target
    mixup_image, mixup_target = mixup_prepared
    return (
        blend_yolov8_mixup_images(
            imports=imports,
            image=image,
            other_image=mixup_image,
        ),
        _merge_yolov8_obb_targets(primary=target, other=mixup_target),
    )


def _prepare_yolov8_obb_mixup_sample(
    *,
    imports: Any,
    sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: YoloV8TaskAugmentationOptions,
) -> tuple[Any, YoloV8ObbPreparedTarget] | None:
    """构造 MixUp 的第二张 OBB 样本。"""

    if augmentation_options.mosaic_prob > 0.0 and random.random() < augmentation_options.mosaic_prob:
        return _build_yolov8_obb_mosaic_sample(
            imports=imports,
            primary_sample=sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    return _prepare_yolov8_obb_single_sample(
        imports=imports,
        sample=sample,
        output_size=(target_width, target_height),
        scale_gain=random.uniform(*augmentation_options.mixup_scale),
    )


def _build_yolov8_obb_mosaic_sample(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: YoloV8TaskAugmentationOptions,
) -> tuple[Any, YoloV8ObbPreparedTarget] | None:
    """按 Mosaic4 placement 同步构造 OBB xywhr target。"""

    merged_target: YoloV8ObbPreparedTarget | None = None
    selected_samples = [primary_sample]
    selected_samples.extend(
        random.choice(tuple(available_samples) or (primary_sample,))
        for _ in range(3)
    )
    selected_items: list[tuple[Any, Any]] = []
    for sample in selected_samples:
        image = imports.cv2.imread(str(sample.image_path))
        if image is not None:
            selected_items.append((sample, image))
    if not selected_items:
        return None

    canvas, placements = build_yolo_mosaic4_canvas(
        cv2_module=imports.cv2,
        np_module=imports.np,
        images=tuple(image for _, image in selected_items),
        input_size=(target_height, target_width),
    )
    for placement in placements:
        sample = selected_items[placement.index][0]
        placed_target = _build_yolov8_obb_sample_targets(
            sample=sample,
            resize_ratio=placement.resize_scale,
            pad_xy=(int(placement.offset_x), int(placement.offset_y)),
        )
        placed_target = _filter_yolov8_obb_target(placed_target)
        merged_target = (
            placed_target
            if merged_target is None
            else _merge_yolov8_obb_targets(
                primary=merged_target,
                other=placed_target,
            )
        )
    if merged_target is None:
        return None
    return canvas, merged_target


def _prepare_yolov8_obb_single_sample(
    *,
    imports: Any,
    sample: Any,
    output_size: tuple[int, int],
    scale_gain: float,
) -> tuple[Any, YoloV8ObbPreparedTarget] | None:
    """把单张 OBB 样本缩放到指定画布。"""

    image = imports.cv2.imread(str(sample.image_path))
    if image is None:
        return None
    target_width, target_height = int(output_size[0]), int(output_size[1])
    canvas, resize_ratio, pad_xy = resize_yolov8_image_to_canvas(
        imports=imports,
        image=image,
        output_size=(target_width, target_height),
        scale_gain=scale_gain,
    )
    return canvas, _build_yolov8_obb_sample_targets(
        sample=sample,
        resize_ratio=resize_ratio,
        pad_xy=pad_xy,
    )


def _build_yolov8_obb_sample_targets(
    *,
    sample: Any,
    resize_ratio: float,
    pad_xy: tuple[int, int],
) -> YoloV8ObbPreparedTarget:
    """构造单张图的 YOLOv8 OBB target。"""

    scaled_boxes: list[list[float]] = []
    category_indexes: list[int] = []
    for box_xywhr, class_id in zip(sample.boxes_xywhr, sample.class_ids, strict=True):
        cx, cy, width, height, angle = box_xywhr
        scaled_width = width * resize_ratio
        scaled_height = height * resize_ratio
        if scaled_width < 2.0 or scaled_height < 2.0:
            continue
        scaled_boxes.append(
            [
                cx * resize_ratio + pad_xy[0],
                cy * resize_ratio + pad_xy[1],
                scaled_width,
                scaled_height,
                angle,
            ]
        )
        category_indexes.append(int(class_id))
    return YoloV8ObbPreparedTarget(
        boxes_xywhr=scaled_boxes,
        category_indexes=category_indexes,
    )


def _merge_yolov8_obb_targets(
    *,
    primary: YoloV8ObbPreparedTarget,
    other: YoloV8ObbPreparedTarget,
) -> YoloV8ObbPreparedTarget:
    """合并两组 OBB targets。"""

    return _filter_yolov8_obb_target(
        YoloV8ObbPreparedTarget(
            boxes_xywhr=list(primary.boxes_xywhr) + list(other.boxes_xywhr),
            category_indexes=list(primary.category_indexes) + list(other.category_indexes),
        )
    )


def _filter_yolov8_obb_target(
    target: YoloV8ObbPreparedTarget,
) -> YoloV8ObbPreparedTarget:
    """过滤退化的 YOLOv8 OBB targets。"""

    kept_indices: list[int] = []
    kept_boxes: list[list[float]] = []
    for box_index, box in enumerate(target.boxes_xywhr):
        width, height = float(box[2]), float(box[3])
        if width < 2.0 or height < 2.0:
            continue
        kept_indices.append(box_index)
        kept_boxes.append(
            [
                float(box[0]),
                float(box[1]),
                width,
                height,
                normalize_yolov8_obb_angle(float(box[4])),
            ]
        )
    return YoloV8ObbPreparedTarget(
        boxes_xywhr=kept_boxes,
        category_indexes=select_yolov8_items_by_indices(
            list(target.category_indexes),
            kept_indices,
        ),
    )


def _apply_yolov8_obb_augmentation(
    *,
    image: Any,
    target: YoloV8ObbPreparedTarget,
    target_width: int,
    target_height: int,
    imports: Any,
    augmentation_options: YoloV8TaskAugmentationOptions | None,
) -> tuple[Any, YoloV8ObbPreparedTarget]:
    """对 YOLOv8 OBB 图像和 rotated target 执行受控增强。"""

    if augmentation_options is None:
        return image, target
    image, target = _apply_yolov8_obb_random_affine(
        imports=imports,
        image=image,
        target=target,
        target_width=target_width,
        target_height=target_height,
        augmentation_options=augmentation_options,
    )
    image = apply_yolov8_random_hsv(
        imports=imports,
        image=image,
        hsv_prob=augmentation_options.hsv_prob,
    )
    if not should_apply_yolov8_horizontal_flip(augmentation_options.flip_prob):
        return image, target
    flipped_boxes = [
        [
            target_width - box[0],
            box[1],
            box[2],
            box[3],
            normalize_yolov8_obb_angle(-box[4]),
        ]
        for box in target.boxes_xywhr
    ]
    return (
        flip_yolov8_image_horizontally(image),
        YoloV8ObbPreparedTarget(
            boxes_xywhr=flipped_boxes,
            category_indexes=list(target.category_indexes),
        ),
    )


def _apply_yolov8_obb_random_affine(
    *,
    imports: Any,
    image: Any,
    target: YoloV8ObbPreparedTarget,
    target_width: int,
    target_height: int,
    augmentation_options: YoloV8TaskAugmentationOptions,
) -> tuple[Any, YoloV8ObbPreparedTarget]:
    """对 OBB rotated target 同步执行 random affine。"""

    image, matrix, applied = apply_yolov8_random_affine(
        imports=imports,
        image=image,
        output_size=(target_width, target_height),
        augmentation_options=augmentation_options,
    )
    if not applied or matrix is None:
        return image, target
    transformed_boxes, kept_indices = transform_yolov8_obb_boxes(
        imports=imports,
        boxes_xywhr=target.boxes_xywhr,
        matrix=matrix,
        output_size=(target_width, target_height),
        perspective=augmentation_options.perspective,
    )
    return (
        image,
        YoloV8ObbPreparedTarget(
            boxes_xywhr=transformed_boxes,
            category_indexes=select_yolov8_items_by_indices(
                list(target.category_indexes),
                kept_indices,
            ),
        ),
    )


__all__ = [
    "YoloV8ObbPreparedTarget",
    "YoloV8ObbTrainingBatch",
    "build_yolov8_obb_training_batch",
]
