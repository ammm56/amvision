"""YOLO26 segmentation 训练和评估 batch 编码。"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolo26_core.data.augmentation import (
    Yolo26TaskAugmentationOptions,
    apply_yolo26_random_affine,
    apply_yolo26_random_hsv,
    blend_yolo26_mixup_images,
    flip_yolo26_image_horizontally,
    resize_yolo26_image_to_canvas,
    select_yolo26_items_by_indices,
    should_apply_yolo26_horizontal_flip,
    transform_yolo26_boxes_xyxy,
    warp_yolo26_masks,
)
from backend.service.application.models.yolo26_core.targets import (
    rasterize_yolo26_segmentation_polygons,
    select_yolo26_object_segmentation_polygons,
)


@dataclass(frozen=True)
class Yolo26SegmentationTrainingBatch:
    """描述 YOLO26 segmentation 训练或评估使用的 batch。"""

    images: Any
    targets: list[dict[str, Any]]


def build_yolo26_segmentation_training_batch(
    *,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
    augmentation_options: Yolo26TaskAugmentationOptions | None = None,
    available_samples: Sequence[Any] | None = None,
) -> Yolo26SegmentationTrainingBatch | None:
    """把样本列表编码为 YOLO26 segmentation 训练 batch。

    本入口负责 polygon 选择、mask target 栅格化，以及当前 batch
    的 mosaic、mixup、random affine、HSV 和 flip 增强。
    """

    if not samples:
        return None

    images: list[Any] = []
    targets: list[dict[str, Any]] = []
    target_width, target_height = input_size
    resolved_available_samples = tuple(available_samples or samples)
    for sample in samples:
        prepared = _prepare_yolo26_segmentation_sample_with_mix(
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
        canvas, target = _apply_yolo26_segmentation_augmentation(
            imports=imports,
            image=canvas,
            target=target,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
        target = _finalize_yolo26_segmentation_target(
            imports=imports,
            target=target,
            device=device,
        )

        tensor = (
            canvas[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        )
        image_tensor = imports.torch.from_numpy(tensor).to(device).float()
        if precision == "fp16":
            image_tensor = image_tensor.half()
        images.append(image_tensor)
        targets.append(target)

    if not images:
        return None
    return Yolo26SegmentationTrainingBatch(
        images=imports.torch.stack(images, dim=0),
        targets=targets,
    )


def _prepare_yolo26_segmentation_sample_with_mix(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo26TaskAugmentationOptions | None,
) -> tuple[Any, dict[str, Any]] | None:
    """构造可能包含 mosaic / mixup 的 segmentation 样本。"""

    if (
        augmentation_options is not None
        and augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        prepared = _build_yolo26_segmentation_mosaic_sample(
            imports=imports,
            primary_sample=primary_sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    else:
        prepared = _prepare_yolo26_segmentation_single_sample(
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
    mixup_prepared = _prepare_yolo26_segmentation_mixup_sample(
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
        blend_yolo26_mixup_images(
            imports=imports,
            image=image,
            other_image=mixup_image,
        ),
        _merge_yolo26_segmentation_targets(
            imports=imports,
            primary=target,
            other=mixup_target,
            target_width=target_width,
            target_height=target_height,
        ),
    )


def _prepare_yolo26_segmentation_mixup_sample(
    *,
    imports: Any,
    sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo26TaskAugmentationOptions,
) -> tuple[Any, dict[str, Any]] | None:
    """构造 MixUp 的第二张 segmentation 样本。"""

    if (
        augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        return _build_yolo26_segmentation_mosaic_sample(
            imports=imports,
            primary_sample=sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    return _prepare_yolo26_segmentation_single_sample(
        imports=imports,
        sample=sample,
        output_size=(target_width, target_height),
        scale_gain=random.uniform(*augmentation_options.mixup_scale),
    )


def _build_yolo26_segmentation_mosaic_sample(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo26TaskAugmentationOptions,
) -> tuple[Any, dict[str, Any]] | None:
    """构造 2x2 YOLO26 segmentation mosaic 样本。"""

    top_height = target_height // 2
    left_width = target_width // 2
    placements = (
        (0, 0, left_width, top_height),
        (left_width, 0, target_width - left_width, top_height),
        (0, top_height, left_width, target_height - top_height),
        (left_width, top_height, target_width - left_width, target_height - top_height),
    )
    canvas = imports.np.full(
        (target_height, target_width, 3), 114, dtype=imports.np.uint8
    )
    merged_target: dict[str, Any] | None = None
    selected_samples = [primary_sample]
    selected_samples.extend(
        random.choice(tuple(available_samples) or (primary_sample,)) for _ in range(3)
    )
    for sample, (left, top, cell_width, cell_height) in zip(
        selected_samples, placements, strict=True
    ):
        prepared = _prepare_yolo26_segmentation_single_sample(
            imports=imports,
            sample=sample,
            output_size=(cell_width, cell_height),
            scale_gain=random.uniform(*augmentation_options.mosaic_scale),
        )
        if prepared is None:
            continue
        cell_image, cell_target = prepared
        canvas[top : top + cell_height, left : left + cell_width] = cell_image
        shifted_target = _offset_yolo26_segmentation_target(
            imports=imports,
            target=cell_target,
            offset_xy=(left, top),
            output_size=(target_width, target_height),
        )
        merged_target = (
            shifted_target
            if merged_target is None
            else _merge_yolo26_segmentation_targets(
                imports=imports,
                primary=merged_target,
                other=shifted_target,
                target_width=target_width,
                target_height=target_height,
            )
        )
    if merged_target is None:
        return None
    return canvas, merged_target


def _prepare_yolo26_segmentation_single_sample(
    *,
    imports: Any,
    sample: Any,
    output_size: tuple[int, int],
    scale_gain: float,
) -> tuple[Any, dict[str, Any]] | None:
    """把单张 segmentation 样本缩放到指定画布。"""

    image = imports.cv2.imread(str(sample.image_path))
    if image is None:
        return None
    target_width, target_height = int(output_size[0]), int(output_size[1])
    canvas, resize_ratio, pad_xy = resize_yolo26_image_to_canvas(
        imports=imports,
        image=image,
        output_size=(target_width, target_height),
        scale_gain=scale_gain,
    )
    return canvas, _build_yolo26_segmentation_sample_targets(
        sample=sample,
        target_width=target_width,
        target_height=target_height,
        resize_ratio=resize_ratio,
        pad_xy=pad_xy,
        imports=imports,
    )


def _build_yolo26_segmentation_sample_targets(
    *,
    sample: Any,
    target_width: int,
    target_height: int,
    resize_ratio: float,
    pad_xy: tuple[int, int],
    imports: Any,
) -> dict[str, Any]:
    """构造单张图的 YOLO26 segmentation target。"""

    box_targets: list[list[float]] = []
    class_targets: list[int] = []
    mask_targets: list[Any] = []
    mask_valid: list[bool] = []
    object_count = len(sample.boxes_xywh)
    for object_index, (bbox, class_id) in enumerate(
        zip(sample.boxes_xywh, sample.class_ids, strict=True)
    ):
        x, y, width, height = bbox
        x1 = x * resize_ratio + pad_xy[0]
        y1 = y * resize_ratio + pad_xy[1]
        x2 = (x + width) * resize_ratio + pad_xy[0]
        y2 = (y + height) * resize_ratio + pad_xy[1]
        box_targets.append([x1, y1, x2, y2])
        class_targets.append(int(class_id))

        polygons = select_yolo26_object_segmentation_polygons(
            sample.segmentations,
            object_index=object_index,
            object_count=object_count,
        )
        mask, valid = rasterize_yolo26_segmentation_polygons(
            cv2_module=imports.cv2,
            np_module=imports.np,
            polygons=polygons,
            output_size=(target_width, target_height),
            resize_scale=resize_ratio,
            pad_xy=pad_xy,
        )
        mask_targets.append(mask)
        mask_valid.append(valid)

    target_payload: dict[str, Any] = {
        "boxes": box_targets,
        "class_ids": class_targets,
    }
    if mask_targets:
        target_payload["masks_array"] = imports.np.stack(mask_targets, axis=0)
        target_payload["mask_valid_array"] = imports.np.asarray(
            mask_valid, dtype=imports.np.bool_
        )
    return target_payload


def _offset_yolo26_segmentation_target(
    *,
    imports: Any,
    target: dict[str, Any],
    offset_xy: tuple[int, int],
    output_size: tuple[int, int],
) -> dict[str, Any]:
    """把 cell 内 segmentation target 平移到 mosaic 画布。"""

    offset_x, offset_y = int(offset_xy[0]), int(offset_xy[1])
    output_width, output_height = int(output_size[0]), int(output_size[1])
    shifted = dict(target)
    shifted["boxes"] = [
        [
            max(0.0, min(float(box[0]) + offset_x, float(output_width))),
            max(0.0, min(float(box[1]) + offset_y, float(output_height))),
            max(0.0, min(float(box[2]) + offset_x, float(output_width))),
            max(0.0, min(float(box[3]) + offset_y, float(output_height))),
        ]
        for box in target.get("boxes", [])
    ]
    masks = target.get("masks_array")
    if masks is not None:
        shifted_masks = imports.np.zeros(
            (masks.shape[0], output_height, output_width),
            dtype=masks.dtype,
        )
        source_height, source_width = int(masks.shape[1]), int(masks.shape[2])
        shifted_masks[
            :, offset_y : offset_y + source_height, offset_x : offset_x + source_width
        ] = masks[
            :,
            : min(source_height, output_height - offset_y),
            : min(source_width, output_width - offset_x),
        ]
        shifted["masks_array"] = shifted_masks
    return _filter_yolo26_segmentation_target_by_boxes(
        imports=imports,
        target=shifted,
    )


def _merge_yolo26_segmentation_targets(
    *,
    imports: Any,
    primary: dict[str, Any],
    other: dict[str, Any],
    target_width: int,
    target_height: int,
) -> dict[str, Any]:
    """合并两组 segmentation targets。"""

    merged = {
        "boxes": list(primary.get("boxes", [])) + list(other.get("boxes", [])),
        "class_ids": list(primary.get("class_ids", []))
        + list(other.get("class_ids", [])),
    }
    primary_masks = primary.get("masks_array")
    other_masks = other.get("masks_array")
    if primary_masks is not None or other_masks is not None:
        merged["masks_array"] = imports.np.concatenate(
            [
                _ensure_yolo26_segmentation_masks(
                    imports=imports,
                    masks=primary_masks,
                    count=len(primary.get("boxes", [])),
                    target_width=target_width,
                    target_height=target_height,
                ),
                _ensure_yolo26_segmentation_masks(
                    imports=imports,
                    masks=other_masks,
                    count=len(other.get("boxes", [])),
                    target_width=target_width,
                    target_height=target_height,
                ),
            ],
            axis=0,
        )
        merged["mask_valid_array"] = imports.np.concatenate(
            [
                _ensure_yolo26_mask_valid(
                    imports=imports,
                    mask_valid=primary.get("mask_valid_array"),
                    count=len(primary.get("boxes", [])),
                ),
                _ensure_yolo26_mask_valid(
                    imports=imports,
                    mask_valid=other.get("mask_valid_array"),
                    count=len(other.get("boxes", [])),
                ),
            ],
            axis=0,
        )
    return _filter_yolo26_segmentation_target_by_boxes(
        imports=imports,
        target=merged,
    )


def _ensure_yolo26_segmentation_masks(
    *,
    imports: Any,
    masks: Any,
    count: int,
    target_width: int,
    target_height: int,
) -> Any:
    """补齐用于合并的 segmentation masks。"""

    if masks is not None:
        return masks
    return imports.np.zeros(
        (count, target_height, target_width), dtype=imports.np.float32
    )


def _ensure_yolo26_mask_valid(
    *,
    imports: Any,
    mask_valid: Any,
    count: int,
) -> Any:
    """补齐用于合并的 mask valid 标记。"""

    if mask_valid is not None:
        return mask_valid
    return imports.np.zeros((count,), dtype=imports.np.bool_)


def _filter_yolo26_segmentation_target_by_boxes(
    *,
    imports: Any,
    target: dict[str, Any],
) -> dict[str, Any]:
    """过滤 mosaic / mixup 后退化的 segmentation boxes。"""

    kept_indices: list[int] = []
    kept_boxes: list[list[float]] = []
    for box_index, box in enumerate(target.get("boxes", [])):
        x1, y1, x2, y2 = [float(value) for value in box]
        if x2 - x1 <= 2.0 or y2 - y1 <= 2.0:
            continue
        kept_indices.append(box_index)
        kept_boxes.append([x1, y1, x2, y2])
    filtered = dict(target)
    filtered["boxes"] = kept_boxes
    filtered["class_ids"] = select_yolo26_items_by_indices(
        list(target.get("class_ids", [])),
        kept_indices,
    )
    if "masks_array" in filtered:
        filtered["masks_array"] = filtered["masks_array"][kept_indices]
    if "mask_valid_array" in filtered:
        filtered["mask_valid_array"] = imports.np.asarray(filtered["mask_valid_array"])[
            kept_indices
        ]
    return filtered


def _apply_yolo26_segmentation_augmentation(
    *,
    imports: Any,
    image: Any,
    target: dict[str, Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo26TaskAugmentationOptions | None,
) -> tuple[Any, dict[str, Any]]:
    """对 YOLO26 segmentation 图像和 mask target 执行受控增强。"""

    if augmentation_options is None:
        return image, target
    image, target = _apply_yolo26_segmentation_random_affine(
        imports=imports,
        image=image,
        target=target,
        target_width=target_width,
        target_height=target_height,
        augmentation_options=augmentation_options,
    )
    image = apply_yolo26_random_hsv(
        imports=imports,
        image=image,
        hsv_prob=augmentation_options.hsv_prob,
    )
    if not should_apply_yolo26_horizontal_flip(augmentation_options.flip_prob):
        return image, target
    flipped_target = dict(target)
    flipped_target["boxes"] = [
        [target_width - box[2], box[1], target_width - box[0], box[3]]
        for box in target.get("boxes", [])
    ]
    if "masks_array" in flipped_target:
        flipped_target["masks_array"] = flipped_target["masks_array"][:, :, ::-1].copy()
    return flip_yolo26_image_horizontally(image), flipped_target


def _apply_yolo26_segmentation_random_affine(
    *,
    imports: Any,
    image: Any,
    target: dict[str, Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo26TaskAugmentationOptions,
) -> tuple[Any, dict[str, Any]]:
    """对 segmentation mask 和 bbox 同步执行 random affine。"""

    image, matrix, applied = apply_yolo26_random_affine(
        imports=imports,
        image=image,
        output_size=(target_width, target_height),
        augmentation_options=augmentation_options,
    )
    if not applied or matrix is None:
        return image, target
    boxes = list(target.get("boxes", []))
    masks = target.get("masks_array")
    mask_valid = target.get("mask_valid_array")
    transformed_boxes, transformed_box_indices = transform_yolo26_boxes_xyxy(
        imports=imports,
        boxes_xyxy=boxes,
        matrix=matrix,
        output_size=(target_width, target_height),
        perspective=augmentation_options.perspective,
        area_threshold=0.01,
    )
    if masks is not None:
        warped_masks = warp_yolo26_masks(
            imports=imports,
            masks=masks,
            matrix=matrix,
            output_size=(target_width, target_height),
            perspective=augmentation_options.perspective,
        )
        kept_pairs = _filter_yolo26_segmentation_affine_indices(
            imports=imports,
            transformed_boxes=transformed_boxes,
            transformed_box_indices=transformed_box_indices,
            warped_masks=warped_masks,
            mask_valid=mask_valid,
        )
        kept_boxes = [box for box, _ in kept_pairs]
        kept_indices = [original_index for _, original_index in kept_pairs]
    else:
        warped_masks = None
        kept_boxes = transformed_boxes
        kept_indices = transformed_box_indices
    transformed_target = dict(target)
    transformed_target["boxes"] = kept_boxes
    transformed_target["class_ids"] = select_yolo26_items_by_indices(
        list(target.get("class_ids", [])),
        kept_indices,
    )
    if warped_masks is not None:
        transformed_target["masks_array"] = warped_masks[kept_indices]
        transformed_target["mask_valid_array"] = target.get("mask_valid_array")[
            kept_indices
        ]
    return image, transformed_target


def _filter_yolo26_segmentation_affine_indices(
    *,
    imports: Any,
    transformed_boxes: list[list[float]],
    transformed_box_indices: list[int],
    warped_masks: Any,
    mask_valid: Any,
) -> list[tuple[list[float], int]]:
    """按 bbox 和 mask 有效性过滤 segmentation affine 后的目标。"""

    kept_pairs: list[tuple[list[float], int]] = []
    for transformed_box, original_index in zip(
        transformed_boxes,
        transformed_box_indices,
        strict=False,
    ):
        if mask_valid is not None and bool(mask_valid[original_index]):
            if int(imports.np.count_nonzero(warped_masks[original_index] > 0.5)) == 0:
                continue
        kept_pairs.append((transformed_box, original_index))
    return kept_pairs


def _finalize_yolo26_segmentation_target(
    *,
    imports: Any,
    target: dict[str, Any],
    device: str,
) -> dict[str, Any]:
    """把 segmentation target 的 Numpy mask 转为 torch tensor。"""

    finalized = dict(target)
    masks = finalized.pop("masks_array", None)
    mask_valid = finalized.pop("mask_valid_array", None)
    if masks is not None:
        finalized["masks"] = imports.torch.from_numpy(masks).to(device)
        finalized["mask_valid"] = imports.torch.tensor(
            mask_valid,
            dtype=imports.torch.bool,
            device=device,
        )
    return finalized
