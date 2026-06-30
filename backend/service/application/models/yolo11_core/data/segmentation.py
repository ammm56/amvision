"""YOLO11 segmentation 训练和评估 batch 编码。"""

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
from backend.service.application.models.yolo11_core.data.augmentation import (
    Yolo11TaskAugmentationOptions,
    apply_yolo11_random_affine,
    apply_yolo11_random_hsv,
    blend_yolo11_mixup_images,
    flip_yolo11_image_horizontally,
    resize_yolo11_image_to_canvas,
    select_yolo11_items_by_indices,
    should_apply_yolo11_horizontal_flip,
    transform_yolo11_boxes_xyxy,
    warp_yolo11_masks,
)
from backend.service.application.models.yolo11_core.targets import (
    rasterize_yolo11_segmentation_polygons,
    select_yolo11_object_segmentation_polygons,
)


@dataclass(frozen=True)
class Yolo11SegmentationTrainingBatch:
    """描述 YOLO11 segmentation 训练或评估使用的 batch。"""

    images: Any
    targets: list[dict[str, Any]]


def build_yolo11_segmentation_training_batch(
    *,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
    augmentation_options: Yolo11TaskAugmentationOptions | None = None,
    available_samples: Sequence[Any] | None = None,
) -> Yolo11SegmentationTrainingBatch | None:
    """把样本列表编码为 YOLO11 segmentation 训练 batch。

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
        prepared = _prepare_yolo11_segmentation_sample_with_mix(
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
        canvas, target = _apply_yolo11_segmentation_augmentation(
            imports=imports,
            image=canvas,
            target=target,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
        target = _finalize_yolo11_segmentation_target(
            imports=imports,
            target=target,
            device=device,
        )

        tensor = (
            canvas[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        )
        images.append(imports.torch.from_numpy(tensor).float())
        targets.append(target)

    if not images:
        return None
    return Yolo11SegmentationTrainingBatch(
        images=move_yolo_tensor_to_training_device(
            imports.torch.stack(images, dim=0),
            device=device,
            runtime_precision=precision,
        ),
        targets=targets,
    )


def _prepare_yolo11_segmentation_sample_with_mix(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions | None,
) -> tuple[Any, dict[str, Any]] | None:
    """构造可能包含 mosaic / mixup 的 segmentation 样本。"""

    if (
        augmentation_options is not None
        and augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        prepared = _build_yolo11_segmentation_mosaic_sample(
            imports=imports,
            primary_sample=primary_sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    else:
        prepared = _prepare_yolo11_segmentation_single_sample(
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
    mixup_prepared = _prepare_yolo11_segmentation_mixup_sample(
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
        blend_yolo11_mixup_images(
            imports=imports,
            image=image,
            other_image=mixup_image,
        ),
        _merge_yolo11_segmentation_targets(
            imports=imports,
            primary=target,
            other=mixup_target,
            target_width=target_width,
            target_height=target_height,
        ),
    )


def _prepare_yolo11_segmentation_mixup_sample(
    *,
    imports: Any,
    sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, dict[str, Any]] | None:
    """构造 MixUp 的第二张 segmentation 样本。"""

    if (
        augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        return _build_yolo11_segmentation_mosaic_sample(
            imports=imports,
            primary_sample=sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    return _prepare_yolo11_segmentation_single_sample(
        imports=imports,
        sample=sample,
        output_size=(target_width, target_height),
        scale_gain=random.uniform(*augmentation_options.mixup_scale),
    )


def _build_yolo11_segmentation_mosaic_sample(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, dict[str, Any]] | None:
    """按 Mosaic4 placement 同步构造 segmentation mask 和 bbox target。"""

    merged_target: dict[str, Any] | None = None
    selected_samples = [primary_sample]
    selected_samples.extend(
        random.choice(tuple(available_samples) or (primary_sample,)) for _ in range(3)
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
        placed_target = _build_yolo11_segmentation_sample_targets(
            sample=sample,
            target_width=placement.canvas_width,
            target_height=placement.canvas_height,
            resize_ratio=placement.resize_scale,
            pad_xy=(int(placement.offset_x), int(placement.offset_y)),
            imports=imports,
        )
        placed_target = _filter_yolo11_segmentation_target_by_boxes(
            imports=imports,
            target=placed_target,
        )
        merged_target = (
            placed_target
            if merged_target is None
            else _merge_yolo11_segmentation_targets(
                imports=imports,
                primary=merged_target,
                other=placed_target,
                target_width=placement.canvas_width,
                target_height=placement.canvas_height,
            )
        )
    if merged_target is None:
        return None
    return canvas, merged_target


def _prepare_yolo11_segmentation_single_sample(
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
    canvas, resize_ratio, pad_xy = resize_yolo11_image_to_canvas(
        imports=imports,
        image=image,
        output_size=(target_width, target_height),
        scale_gain=scale_gain,
    )
    return canvas, _build_yolo11_segmentation_sample_targets(
        sample=sample,
        target_width=target_width,
        target_height=target_height,
        resize_ratio=resize_ratio,
        pad_xy=pad_xy,
        imports=imports,
    )


def _build_yolo11_segmentation_sample_targets(
    *,
    sample: Any,
    target_width: int,
    target_height: int,
    resize_ratio: float,
    pad_xy: tuple[int, int],
    imports: Any,
) -> dict[str, Any]:
    """构造单张图的 YOLO11 segmentation target。"""

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

        polygons = select_yolo11_object_segmentation_polygons(
            sample.segmentations,
            object_index=object_index,
            object_count=object_count,
        )
        mask, valid = rasterize_yolo11_segmentation_polygons(
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


def _merge_yolo11_segmentation_targets(
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
                _ensure_yolo11_segmentation_masks(
                    imports=imports,
                    masks=primary_masks,
                    count=len(primary.get("boxes", [])),
                    target_width=target_width,
                    target_height=target_height,
                ),
                _ensure_yolo11_segmentation_masks(
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
                _ensure_yolo11_mask_valid(
                    imports=imports,
                    mask_valid=primary.get("mask_valid_array"),
                    count=len(primary.get("boxes", [])),
                ),
                _ensure_yolo11_mask_valid(
                    imports=imports,
                    mask_valid=other.get("mask_valid_array"),
                    count=len(other.get("boxes", [])),
                ),
            ],
            axis=0,
        )
    return _filter_yolo11_segmentation_target_by_boxes(
        imports=imports,
        target=merged,
    )


def _ensure_yolo11_segmentation_masks(
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


def _ensure_yolo11_mask_valid(
    *,
    imports: Any,
    mask_valid: Any,
    count: int,
) -> Any:
    """补齐用于合并的 mask valid 标记。"""

    if mask_valid is not None:
        return mask_valid
    return imports.np.zeros((count,), dtype=imports.np.bool_)


def _filter_yolo11_segmentation_target_by_boxes(
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
    filtered["class_ids"] = select_yolo11_items_by_indices(
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


def _apply_yolo11_segmentation_augmentation(
    *,
    imports: Any,
    image: Any,
    target: dict[str, Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions | None,
) -> tuple[Any, dict[str, Any]]:
    """对 YOLO11 segmentation 图像和 mask target 执行受控增强。"""

    if augmentation_options is None:
        return image, target
    image, target = _apply_yolo11_segmentation_random_affine(
        imports=imports,
        image=image,
        target=target,
        target_width=target_width,
        target_height=target_height,
        augmentation_options=augmentation_options,
    )
    image = apply_yolo11_random_hsv(
        imports=imports,
        image=image,
        hsv_prob=augmentation_options.hsv_prob,
    )
    if not should_apply_yolo11_horizontal_flip(augmentation_options.flip_prob):
        return image, target
    flipped_target = dict(target)
    flipped_target["boxes"] = [
        [target_width - box[2], box[1], target_width - box[0], box[3]]
        for box in target.get("boxes", [])
    ]
    if "masks_array" in flipped_target:
        flipped_target["masks_array"] = flipped_target["masks_array"][:, :, ::-1].copy()
    return flip_yolo11_image_horizontally(image), flipped_target


def _apply_yolo11_segmentation_random_affine(
    *,
    imports: Any,
    image: Any,
    target: dict[str, Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, dict[str, Any]]:
    """对 segmentation mask 和 bbox 同步执行 random affine。"""

    image, matrix, applied = apply_yolo11_random_affine(
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
    transformed_boxes, transformed_box_indices = transform_yolo11_boxes_xyxy(
        imports=imports,
        boxes_xyxy=boxes,
        matrix=matrix,
        output_size=(target_width, target_height),
        perspective=augmentation_options.perspective,
        area_threshold=0.01,
    )
    if masks is not None:
        warped_masks = warp_yolo11_masks(
            imports=imports,
            masks=masks,
            matrix=matrix,
            output_size=(target_width, target_height),
            perspective=augmentation_options.perspective,
        )
        kept_pairs = _filter_yolo11_segmentation_affine_indices(
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
    transformed_target["class_ids"] = select_yolo11_items_by_indices(
        list(target.get("class_ids", [])),
        kept_indices,
    )
    if warped_masks is not None:
        transformed_target["masks_array"] = warped_masks[kept_indices]
        transformed_target["mask_valid_array"] = target.get("mask_valid_array")[
            kept_indices
        ]
    return image, transformed_target


def _filter_yolo11_segmentation_affine_indices(
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


def _finalize_yolo11_segmentation_target(
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
        finalized["masks"] = move_yolo_tensor_to_training_device(
            imports.torch.from_numpy(masks),
            device=device,
        )
        finalized["mask_valid"] = imports.torch.tensor(
            mask_valid,
            dtype=imports.torch.bool,
            device=device,
        )
    return finalized
