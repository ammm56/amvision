"""YOLO11 pose 训练和评估 batch 编码。"""

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
from backend.service.application.models.yolo_core_common.training.task_dataloader import (
    pin_yolo_task_value,
)
from backend.service.application.models.yolo11_core.data.augmentation import (
    Yolo11TaskAugmentationOptions,
    apply_yolo11_random_affine,
    apply_yolo11_random_hsv,
    blend_yolo11_mixup_images,
    flip_yolo11_image_horizontally,
    resize_yolo11_image_to_canvas,
    resolve_yolo11_pose_flip_indices,
    select_yolo11_items_by_indices,
    should_apply_yolo11_horizontal_flip,
    transform_yolo11_boxes_xyxy,
    transform_yolo11_keypoints,
)


@dataclass(frozen=True)
class Yolo11PosePreparedTarget:
    """描述单张图的 YOLO11 pose 训练目标。"""

    boxes_xyxy: list[list[float]]
    category_indexes: list[int]
    keypoints: list[list[float]] | None = None


@dataclass(frozen=True)
class Yolo11PoseTrainingBatch:
    """描述 YOLO11 pose 训练或评估使用的 batch。"""

    images: Any
    targets: tuple[Yolo11PosePreparedTarget, ...]

    def pin_memory(self) -> "Yolo11PoseTrainingBatch":
        """让 PyTorch DataLoader 能对自定义 batch 执行 pinned memory。"""

        return Yolo11PoseTrainingBatch(
            images=pin_yolo_task_value(self.images),
            targets=pin_yolo_task_value(self.targets),
        )


def build_yolo11_pose_training_batch(
    *,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
    augmentation_options: Yolo11TaskAugmentationOptions | None = None,
    available_samples: Sequence[Any] | None = None,
) -> Yolo11PoseTrainingBatch | None:
    """把样本列表编码为 YOLO11 pose 训练 batch。"""

    if not samples:
        return None

    target_width, target_height = input_size
    images: list[Any] = []
    targets: list[Yolo11PosePreparedTarget] = []
    resolved_available_samples = tuple(available_samples or samples)
    for sample in samples:
        prepared = _prepare_yolo11_pose_sample_with_mix(
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
        canvas, target = _apply_yolo11_pose_augmentation(
            image=canvas,
            target=target,
            target_width=target_width,
            target_height=target_height,
            imports=imports,
            augmentation_options=augmentation_options,
        )
        tensor = (
            canvas[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        )
        images.append(imports.torch.from_numpy(tensor).float())
        targets.append(target)

    if not images:
        return None
    return Yolo11PoseTrainingBatch(
        images=move_yolo_tensor_to_training_device(
            imports.torch.stack(images, dim=0),
            device=device,
            runtime_precision=precision,
        ),
        targets=tuple(targets),
    )


def _prepare_yolo11_pose_sample_with_mix(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions | None,
) -> tuple[Any, Yolo11PosePreparedTarget] | None:
    """构造可能包含 mosaic / mixup 的 YOLO11 pose 样本。"""

    if (
        augmentation_options is not None
        and augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        prepared = _build_yolo11_pose_mosaic_sample(
            imports=imports,
            primary_sample=primary_sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    else:
        prepared = _prepare_yolo11_pose_single_sample(
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
    mixup_prepared = _prepare_yolo11_pose_mixup_sample(
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
        _merge_yolo11_pose_targets(primary=target, other=mixup_target),
    )


def _prepare_yolo11_pose_mixup_sample(
    *,
    imports: Any,
    sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, Yolo11PosePreparedTarget] | None:
    """构造 MixUp 的第二张 YOLO11 pose 样本。"""

    if (
        augmentation_options.mosaic_prob > 0.0
        and random.random() < augmentation_options.mosaic_prob
    ):
        return _build_yolo11_pose_mosaic_sample(
            imports=imports,
            primary_sample=sample,
            available_samples=available_samples,
            target_width=target_width,
            target_height=target_height,
            augmentation_options=augmentation_options,
        )
    return _prepare_yolo11_pose_single_sample(
        imports=imports,
        sample=sample,
        output_size=(target_width, target_height),
        scale_gain=random.uniform(*augmentation_options.mixup_scale),
    )


def _build_yolo11_pose_mosaic_sample(
    *,
    imports: Any,
    primary_sample: Any,
    available_samples: Sequence[Any],
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, Yolo11PosePreparedTarget] | None:
    """按 Mosaic4 placement 同步构造 pose bbox 和 keypoint target。"""

    merged_target: Yolo11PosePreparedTarget | None = None
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
        placed_target = _build_yolo11_pose_sample_targets(
            sample=sample,
            resize_ratio=placement.resize_scale,
            pad_xy=(int(placement.offset_x), int(placement.offset_y)),
        )
        placed_target = _filter_yolo11_pose_target(placed_target)
        merged_target = (
            placed_target
            if merged_target is None
            else _merge_yolo11_pose_targets(primary=merged_target, other=placed_target)
        )
    if merged_target is None:
        return None
    return canvas, merged_target


def _prepare_yolo11_pose_single_sample(
    *,
    imports: Any,
    sample: Any,
    output_size: tuple[int, int],
    scale_gain: float,
) -> tuple[Any, Yolo11PosePreparedTarget] | None:
    """把单张 YOLO11 pose 样本缩放到指定画布。"""

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
    return canvas, _build_yolo11_pose_sample_targets(
        sample=sample,
        resize_ratio=resize_ratio,
        pad_xy=pad_xy,
    )


def _build_yolo11_pose_sample_targets(
    *,
    sample: Any,
    resize_ratio: float,
    pad_xy: tuple[int, int],
) -> Yolo11PosePreparedTarget:
    """构造单张图的 YOLO11 pose target。"""

    boxes_xyxy: list[list[float]] = []
    class_ids: list[int] = []
    keypoints: list[list[float]] = []
    for object_index, (bbox, class_id) in enumerate(
        zip(sample.boxes_xywh, sample.class_ids, strict=True)
    ):
        x, y, width, height = bbox
        x1 = x * resize_ratio + pad_xy[0]
        y1 = y * resize_ratio + pad_xy[1]
        x2 = (x + width) * resize_ratio + pad_xy[0]
        y2 = (y + height) * resize_ratio + pad_xy[1]
        if x2 - x1 < 2.0 or y2 - y1 < 2.0:
            continue
        boxes_xyxy.append([x1, y1, x2, y2])
        class_ids.append(int(class_id))
        keypoints.append(
            _transform_yolo11_pose_keypoints(
                sample=sample,
                object_index=object_index,
                resize_ratio=resize_ratio,
                pad_xy=pad_xy,
            )
        )
    return Yolo11PosePreparedTarget(
        boxes_xyxy=boxes_xyxy,
        category_indexes=class_ids,
        keypoints=keypoints if keypoints else None,
    )


def _merge_yolo11_pose_targets(
    *,
    primary: Yolo11PosePreparedTarget,
    other: Yolo11PosePreparedTarget,
) -> Yolo11PosePreparedTarget:
    """合并两组 YOLO11 pose targets。"""

    keypoints = None
    if primary.keypoints is not None or other.keypoints is not None:
        keypoints = list(primary.keypoints or [[] for _ in primary.boxes_xyxy])
        keypoints.extend(list(other.keypoints or [[] for _ in other.boxes_xyxy]))
    return _filter_yolo11_pose_target(
        Yolo11PosePreparedTarget(
            boxes_xyxy=list(primary.boxes_xyxy) + list(other.boxes_xyxy),
            category_indexes=list(primary.category_indexes)
            + list(other.category_indexes),
            keypoints=keypoints,
        )
    )


def _filter_yolo11_pose_target(
    target: Yolo11PosePreparedTarget,
) -> Yolo11PosePreparedTarget:
    """过滤退化的 YOLO11 pose boxes，并同步 keypoints。"""

    kept_indices: list[int] = []
    kept_boxes: list[list[float]] = []
    for box_index, box in enumerate(target.boxes_xyxy):
        x1, y1, x2, y2 = [float(value) for value in box]
        if x2 - x1 <= 2.0 or y2 - y1 <= 2.0:
            continue
        kept_indices.append(box_index)
        kept_boxes.append([x1, y1, x2, y2])
    return Yolo11PosePreparedTarget(
        boxes_xyxy=kept_boxes,
        category_indexes=select_yolo11_items_by_indices(
            list(target.category_indexes), kept_indices
        ),
        keypoints=(
            select_yolo11_items_by_indices(list(target.keypoints), kept_indices)
            if target.keypoints is not None
            else None
        ),
    )


def _transform_yolo11_pose_keypoints(
    *,
    sample: Any,
    object_index: int,
    resize_ratio: float,
    pad_xy: tuple[int, int],
) -> list[float]:
    """把单个目标的 keypoints 变换到 letterbox 后坐标。"""

    if not getattr(sample, "keypoints", None):
        return []
    if object_index >= len(sample.keypoints) or not sample.keypoints[object_index]:
        return []
    raw_keypoints = sample.keypoints[object_index]
    transformed: list[float] = []
    for keypoint_index in range(len(raw_keypoints) // 3):
        base_index = keypoint_index * 3
        transformed.extend(
            [
                raw_keypoints[base_index] * resize_ratio + pad_xy[0],
                raw_keypoints[base_index + 1] * resize_ratio + pad_xy[1],
                raw_keypoints[base_index + 2],
            ]
        )
    return transformed


def _apply_yolo11_pose_augmentation(
    *,
    image: Any,
    target: Yolo11PosePreparedTarget,
    target_width: int,
    target_height: int,
    imports: Any,
    augmentation_options: Yolo11TaskAugmentationOptions | None,
) -> tuple[Any, Yolo11PosePreparedTarget]:
    """对 YOLO11 pose 图像和 keypoint target 执行受控增强。"""

    if augmentation_options is None:
        return image, target
    image, target = _apply_yolo11_pose_random_affine(
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
    if not target.keypoints:
        return image, target
    keypoint_count = len(target.keypoints[0]) // 3
    flip_indices = resolve_yolo11_pose_flip_indices(
        keypoint_count=keypoint_count,
        keypoint_flip_indices=augmentation_options.keypoint_flip_indices,
    )
    if flip_indices is None or not should_apply_yolo11_horizontal_flip(
        augmentation_options.flip_prob
    ):
        return image, target
    flipped_boxes = [
        [target_width - box[2], box[1], target_width - box[0], box[3]]
        for box in target.boxes_xyxy
    ]
    flipped_keypoints = [
        _flip_yolo11_pose_keypoints(
            keypoints=keypoints, target_width=target_width, flip_indices=flip_indices
        )
        for keypoints in target.keypoints
    ]
    return (
        flip_yolo11_image_horizontally(image),
        Yolo11PosePreparedTarget(
            boxes_xyxy=flipped_boxes,
            category_indexes=list(target.category_indexes),
            keypoints=flipped_keypoints,
        ),
    )


def _apply_yolo11_pose_random_affine(
    *,
    imports: Any,
    image: Any,
    target: Yolo11PosePreparedTarget,
    target_width: int,
    target_height: int,
    augmentation_options: Yolo11TaskAugmentationOptions,
) -> tuple[Any, Yolo11PosePreparedTarget]:
    """对 YOLO11 pose bbox 和 keypoints 同步执行 random affine。"""

    image, matrix, applied = apply_yolo11_random_affine(
        imports=imports,
        image=image,
        output_size=(target_width, target_height),
        augmentation_options=augmentation_options,
    )
    if not applied or matrix is None:
        return image, target
    transformed_boxes, kept_indices = transform_yolo11_boxes_xyxy(
        imports=imports,
        boxes_xyxy=target.boxes_xyxy,
        matrix=matrix,
        output_size=(target_width, target_height),
        perspective=augmentation_options.perspective,
        area_threshold=0.10,
    )
    transformed_keypoints = (
        select_yolo11_items_by_indices(
            transform_yolo11_keypoints(
                imports=imports,
                keypoints=target.keypoints,
                matrix=matrix,
                output_size=(target_width, target_height),
                perspective=augmentation_options.perspective,
            ),
            kept_indices,
        )
        if target.keypoints
        else None
    )
    return (
        image,
        Yolo11PosePreparedTarget(
            boxes_xyxy=transformed_boxes,
            category_indexes=select_yolo11_items_by_indices(
                list(target.category_indexes), kept_indices
            ),
            keypoints=transformed_keypoints,
        ),
    )


def _flip_yolo11_pose_keypoints(
    *,
    keypoints: list[float],
    target_width: int,
    flip_indices: tuple[int, ...],
) -> list[float]:
    """水平翻转并按 flip index 交换 YOLO11 pose keypoints。"""

    transformed: list[tuple[float, float, float]] = []
    for keypoint_index in range(len(keypoints) // 3):
        base_index = keypoint_index * 3
        transformed.append(
            (
                float(target_width) - float(keypoints[base_index]),
                float(keypoints[base_index + 1]),
                float(keypoints[base_index + 2]),
            )
        )
    reordered: list[float] = []
    for source_index in flip_indices:
        point = transformed[int(source_index)]
        reordered.extend([point[0], point[1], point[2]])
    return reordered


__all__ = [
    "Yolo11PosePreparedTarget",
    "Yolo11PoseTrainingBatch",
    "build_yolo11_pose_training_batch",
]
