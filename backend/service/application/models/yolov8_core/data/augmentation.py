"""YOLOv8 task 数据增强公共工具。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YoloV8TaskAugmentationOptions:
    """描述 YOLOv8 非 detection 任务使用的受控增强参数。"""

    hsv_prob: float = 1.0
    flip_prob: float = 0.5
    mosaic_prob: float = 0.0
    mixup_prob: float = 0.0
    enable_mixup: bool = False
    affine_prob: float = 1.0
    degrees: float = 0.0
    translate: float = 0.1
    scale: float = 0.5
    shear: float = 0.0
    perspective: float = 0.0
    mosaic_scale: tuple[float, float] = (0.5, 1.5)
    mixup_scale: tuple[float, float] = (0.5, 1.5)
    close_mosaic_epochs: int = 0
    multi_scale: bool = False
    multi_scale_range: tuple[float, float] = (0.5, 1.5)
    multi_scale_stride: int = 32
    keypoint_flip_indices: tuple[int, ...] | None = None


def build_yolov8_task_augmentation_options(
    extra_options: dict[str, object] | None,
) -> YoloV8TaskAugmentationOptions:
    """从训练 extra_options 构造 YOLOv8 task 增强参数。"""

    extra = dict(extra_options or {})
    augmentation_disabled = bool(
        extra.get(
            "disable_augmentation",
            extra.get("no_augmentation", extra.get("no_aug", False)),
        )
    )
    if augmentation_disabled:
        return YoloV8TaskAugmentationOptions(
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
            close_mosaic_epochs=0,
            multi_scale=False,
            keypoint_flip_indices=_parse_keypoint_flip_indices(extra.get("keypoint_flip_indices")),
        )

    flip_indices = _parse_keypoint_flip_indices(extra.get("keypoint_flip_indices"))
    multi_scale_value = extra.get("multi_scale", False)
    multi_scale_enabled = (
        bool(multi_scale_value)
        if not isinstance(multi_scale_value, int | float)
        else float(multi_scale_value) > 0.0
    )
    multi_scale_default_range = (
        (1.0 - float(multi_scale_value), 1.0 + float(multi_scale_value))
        if isinstance(multi_scale_value, int | float) and float(multi_scale_value) > 0.0
        else (0.5, 1.5)
    )
    return YoloV8TaskAugmentationOptions(
        hsv_prob=_clamp_probability(
            _read_float_option(extra, "hsv_prob", default=1.0)
        ),
        flip_prob=_clamp_probability(
            _read_float_option(extra, "flip_prob", default=_read_float_option(extra, "fliplr", default=0.5))
        ),
        mosaic_prob=_clamp_probability(
            _read_float_option(extra, "mosaic_prob", default=_read_float_option(extra, "mosaic", default=1.0))
        ),
        mixup_prob=_clamp_probability(
            _read_float_option(extra, "mixup_prob", default=_read_float_option(extra, "mixup", default=0.0))
        ),
        enable_mixup=_read_bool_option(extra, "enable_mixup", default=True),
        affine_prob=_clamp_probability(
            _read_float_option(extra, "affine_prob", default=1.0)
        ),
        degrees=max(0.0, _read_float_option(extra, "degrees", default=0.0)),
        translate=max(0.0, _read_float_option(extra, "translate", default=0.1)),
        scale=max(0.0, _read_float_option(extra, "scale", default=0.5)),
        shear=max(0.0, _read_float_option(extra, "shear", default=0.0)),
        perspective=max(0.0, _read_float_option(extra, "perspective", default=0.0)),
        mosaic_scale=_read_float_pair_option(extra, "mosaic_scale", default=(0.5, 1.5)),
        mixup_scale=_read_float_pair_option(extra, "mixup_scale", default=(0.5, 1.5)),
        close_mosaic_epochs=max(0, int(_read_float_option(extra, "close_mosaic", default=0.0))),
        multi_scale=multi_scale_enabled,
        multi_scale_range=_read_float_pair_option(
            extra,
            "multi_scale_range",
            default=multi_scale_default_range,
        ),
        multi_scale_stride=max(1, int(_read_float_option(extra, "multi_scale_stride", default=32.0))),
        keypoint_flip_indices=flip_indices,
    )


def resolve_yolov8_task_augmentation_for_epoch(
    *,
    augmentation_options: YoloV8TaskAugmentationOptions | None,
    epoch_index: int,
    max_epochs: int,
) -> YoloV8TaskAugmentationOptions | None:
    """按当前 epoch 解析实际生效的 YOLOv8 task 增强参数。"""

    if augmentation_options is None:
        return None
    close_epochs = int(augmentation_options.close_mosaic_epochs)
    if close_epochs <= 0 or int(epoch_index) < max(0, int(max_epochs) - close_epochs):
        return augmentation_options
    return YoloV8TaskAugmentationOptions(
        hsv_prob=augmentation_options.hsv_prob,
        flip_prob=augmentation_options.flip_prob,
        mosaic_prob=0.0,
        mixup_prob=0.0,
        enable_mixup=False,
        affine_prob=augmentation_options.affine_prob,
        degrees=augmentation_options.degrees,
        translate=augmentation_options.translate,
        scale=augmentation_options.scale,
        shear=augmentation_options.shear,
        perspective=augmentation_options.perspective,
        mosaic_scale=augmentation_options.mosaic_scale,
        mixup_scale=augmentation_options.mixup_scale,
        close_mosaic_epochs=augmentation_options.close_mosaic_epochs,
        multi_scale=augmentation_options.multi_scale,
        multi_scale_range=augmentation_options.multi_scale_range,
        multi_scale_stride=augmentation_options.multi_scale_stride,
        keypoint_flip_indices=augmentation_options.keypoint_flip_indices,
    )


def resolve_yolov8_task_batch_input_size(
    *,
    base_input_size: tuple[int, int],
    augmentation_options: YoloV8TaskAugmentationOptions | None,
) -> tuple[int, int]:
    """按 multi-scale 配置解析当前 batch 输入尺寸。"""

    if augmentation_options is None or not augmentation_options.multi_scale:
        return base_input_size
    base_width, base_height = int(base_input_size[0]), int(base_input_size[1])
    scale_min, scale_max = augmentation_options.multi_scale_range
    scale_value = random.uniform(float(scale_min), float(scale_max))
    stride = max(1, int(augmentation_options.multi_scale_stride))
    width = max(stride, int(round(base_width * scale_value / stride)) * stride)
    height = max(stride, int(round(base_height * scale_value / stride)) * stride)
    return width, height


def resize_yolov8_image_to_canvas(
    *,
    imports: Any,
    image: Any,
    output_size: tuple[int, int],
    scale_gain: float = 1.0,
) -> tuple[Any, float, tuple[int, int]]:
    """把图像缩放、裁剪或填充到指定画布。

    ``output_size`` 使用 ``(width, height)``。返回的 ``resize_scale`` 和
    ``pad_xy`` 可直接用于 bbox、polygon、keypoint 和 OBB 同步变换。
    """

    output_width, output_height = int(output_size[0]), int(output_size[1])
    source_height, source_width = int(image.shape[0]), int(image.shape[1])
    base_scale = min(
        float(output_width) / max(1.0, float(source_width)),
        float(output_height) / max(1.0, float(source_height)),
    )
    resize_scale = max(1e-6, base_scale * max(0.01, float(scale_gain)))
    resized_width = max(1, int(round(source_width * resize_scale)))
    resized_height = max(1, int(round(source_height * resize_scale)))
    resized_image = imports.cv2.resize(
        image,
        (resized_width, resized_height),
        interpolation=imports.cv2.INTER_LINEAR,
    )
    canvas = imports.np.full((output_height, output_width, 3), 114, dtype=imports.np.uint8)
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
    return canvas, resize_scale, (target_x - source_x, target_y - source_y)


def blend_yolov8_mixup_images(*, imports: Any, image: Any, other_image: Any) -> Any:
    """按 YOLOv8 MixUp 权重混合两张同尺寸图片。"""

    mixed = image.astype(imports.np.float32) * 0.5 + other_image.astype(imports.np.float32) * 0.5
    return mixed.clip(0.0, 255.0).astype(imports.np.uint8)


def apply_yolov8_random_hsv(*, imports: Any, image: Any, hsv_prob: float) -> Any:
    """按概率执行 YOLOv8 task HSV 抖动。"""

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


def should_apply_yolov8_horizontal_flip(flip_prob: float) -> bool:
    """判断当前样本是否执行水平翻转。"""

    return flip_prob > 0.0 and random.random() < flip_prob


def flip_yolov8_image_horizontally(image: Any) -> Any:
    """水平翻转训练图像。"""

    return image[:, ::-1].copy()


def apply_yolov8_random_affine(
    *,
    imports: Any,
    image: Any,
    output_size: tuple[int, int],
    augmentation_options: YoloV8TaskAugmentationOptions,
) -> tuple[Any, Any | None, bool]:
    """按 YOLOv8 affine 参数变换图像，并返回同步标注用的矩阵。

    参数中的 ``output_size`` 使用 ``(width, height)``，和本文件内的
    几何矩阵计算保持一致。调用方负责把项目上层的输入尺寸转换清楚。
    """

    if not should_apply_yolov8_random_affine(augmentation_options):
        return image, None, False
    matrix = build_yolov8_random_affine_matrix(
        imports=imports,
        image_shape=image.shape,
        output_size=output_size,
        augmentation_options=augmentation_options,
    )
    output_width, output_height = int(output_size[0]), int(output_size[1])
    if augmentation_options.perspective > 0.0:
        transformed_image = imports.cv2.warpPerspective(
            image,
            matrix,
            (output_width, output_height),
            borderValue=(114, 114, 114),
        )
    else:
        transformed_image = imports.cv2.warpAffine(
            image,
            matrix[:2],
            (output_width, output_height),
            flags=imports.cv2.INTER_LINEAR,
            borderValue=(114, 114, 114),
        )
    return transformed_image, matrix, True


def should_apply_yolov8_random_affine(
    augmentation_options: YoloV8TaskAugmentationOptions,
) -> bool:
    """判断当前样本是否执行 YOLOv8 random affine。"""

    has_transform = any(
        float(value) > 0.0
        for value in (
            augmentation_options.degrees,
            augmentation_options.translate,
            augmentation_options.scale,
            augmentation_options.shear,
            augmentation_options.perspective,
        )
    )
    return (
        has_transform
        and augmentation_options.affine_prob > 0.0
        and random.random() < augmentation_options.affine_prob
    )


def build_yolov8_random_affine_matrix(
    *,
    imports: Any,
    image_shape: tuple[int, ...],
    output_size: tuple[int, int],
    augmentation_options: YoloV8TaskAugmentationOptions,
) -> Any:
    """构造 YOLOv8 random affine / perspective 使用的 3x3 矩阵。"""

    source_height, source_width = int(image_shape[0]), int(image_shape[1])
    output_width, output_height = int(output_size[0]), int(output_size[1])

    center_matrix = imports.np.eye(3, dtype=imports.np.float32)
    center_matrix[0, 2] = -float(source_width) / 2.0
    center_matrix[1, 2] = -float(source_height) / 2.0

    perspective_matrix = imports.np.eye(3, dtype=imports.np.float32)
    perspective_value = float(augmentation_options.perspective)
    if perspective_value > 0.0:
        perspective_matrix[2, 0] = random.uniform(-perspective_value, perspective_value)
        perspective_matrix[2, 1] = random.uniform(-perspective_value, perspective_value)

    rotate_scale_matrix = imports.np.eye(3, dtype=imports.np.float32)
    angle = random.uniform(
        -float(augmentation_options.degrees),
        float(augmentation_options.degrees),
    ) if augmentation_options.degrees > 0.0 else 0.0
    scale = random.uniform(
        1.0 - float(augmentation_options.scale),
        1.0 + float(augmentation_options.scale),
    ) if augmentation_options.scale > 0.0 else 1.0
    rotate_scale_matrix[:2] = imports.cv2.getRotationMatrix2D(
        center=(0.0, 0.0),
        angle=angle,
        scale=max(0.01, scale),
    )

    shear_matrix = imports.np.eye(3, dtype=imports.np.float32)
    if augmentation_options.shear > 0.0:
        shear_matrix[0, 1] = math.tan(
            math.radians(
                random.uniform(
                    -float(augmentation_options.shear),
                    float(augmentation_options.shear),
                )
            )
        )
        shear_matrix[1, 0] = math.tan(
            math.radians(
                random.uniform(
                    -float(augmentation_options.shear),
                    float(augmentation_options.shear),
                )
            )
        )

    translate_matrix = imports.np.eye(3, dtype=imports.np.float32)
    translate = float(augmentation_options.translate)
    translate_matrix[0, 2] = random.uniform(0.5 - translate, 0.5 + translate) * float(output_width)
    translate_matrix[1, 2] = random.uniform(0.5 - translate, 0.5 + translate) * float(output_height)
    return translate_matrix @ shear_matrix @ rotate_scale_matrix @ perspective_matrix @ center_matrix


def transform_yolov8_boxes_xyxy(
    *,
    imports: Any,
    boxes_xyxy: list[list[float]] | list[tuple[float, float, float, float]],
    matrix: Any,
    output_size: tuple[int, int],
    perspective: float,
    area_threshold: float,
) -> tuple[list[list[float]], list[int]]:
    """按 affine 矩阵同步变换 bbox，并返回保留的原始索引。"""

    if not boxes_xyxy:
        return [], []
    output_width, output_height = int(output_size[0]), int(output_size[1])
    transformed_boxes: list[list[float]] = []
    kept_indices: list[int] = []
    for box_index, box in enumerate(boxes_xyxy):
        corners = imports.np.array(
            [
                [box[0], box[1], 1.0],
                [box[2], box[1], 1.0],
                [box[2], box[3], 1.0],
                [box[0], box[3], 1.0],
            ],
            dtype=imports.np.float32,
        )
        transformed = _transform_yolov8_points(
            imports=imports,
            points=corners,
            matrix=matrix,
            perspective=perspective,
        )
        transformed_box = _clip_yolov8_box_xyxy(
            box_xyxy=[
                float(transformed[:, 0].min()),
                float(transformed[:, 1].min()),
                float(transformed[:, 0].max()),
                float(transformed[:, 1].max()),
            ],
            output_size=(output_width, output_height),
        )
        if transformed_box is None or not _is_yolov8_box_candidate(
            original_box=box,
            transformed_box=transformed_box,
            area_threshold=area_threshold,
        ):
            continue
        transformed_boxes.append(transformed_box)
        kept_indices.append(box_index)
    return transformed_boxes, kept_indices


def warp_yolov8_masks(
    *,
    imports: Any,
    masks: Any,
    matrix: Any,
    output_size: tuple[int, int],
    perspective: float,
) -> Any:
    """使用 affine 矩阵同步变换 segmentation masks。"""

    output_width, output_height = int(output_size[0]), int(output_size[1])
    if masks is None or len(masks) == 0:
        return masks
    warped_masks = []
    for mask in masks:
        if perspective > 0.0:
            warped = imports.cv2.warpPerspective(
                mask.astype(imports.np.uint8),
                matrix,
                (output_width, output_height),
                flags=imports.cv2.INTER_NEAREST,
                borderValue=0,
            )
        else:
            warped = imports.cv2.warpAffine(
                mask.astype(imports.np.uint8),
                matrix[:2],
                (output_width, output_height),
                flags=imports.cv2.INTER_NEAREST,
                borderValue=0,
            )
        warped_masks.append((warped > 0).astype(imports.np.float32))
    return imports.np.stack(warped_masks, axis=0)


def build_yolov8_boxes_from_masks(
    *,
    imports: Any,
    masks: Any,
    fallback_boxes: list[list[float]],
    mask_valid: Any,
    output_size: tuple[int, int],
) -> tuple[list[list[float]], list[int]]:
    """从增强后的 mask 重新生成 bbox。"""

    output_width, output_height = int(output_size[0]), int(output_size[1])
    boxes: list[list[float]] = []
    kept_indices: list[int] = []
    for mask_index, mask in enumerate(masks):
        valid = bool(mask_valid[mask_index]) if mask_valid is not None else True
        if valid:
            ys, xs = imports.np.where(mask > 0.5)
            if len(xs) > 0 and len(ys) > 0:
                candidate_box = [
                    float(xs.min()),
                    float(ys.min()),
                    float(xs.max() + 1),
                    float(ys.max() + 1),
                ]
                clipped = _clip_yolov8_box_xyxy(
                    box_xyxy=candidate_box,
                    output_size=(output_width, output_height),
                )
                if clipped is not None:
                    boxes.append(clipped)
                    kept_indices.append(mask_index)
                    continue
        if mask_index < len(fallback_boxes):
            clipped = _clip_yolov8_box_xyxy(
                box_xyxy=fallback_boxes[mask_index],
                output_size=(output_width, output_height),
            )
            if clipped is not None:
                boxes.append(clipped)
                kept_indices.append(mask_index)
    return boxes, kept_indices


def transform_yolov8_keypoints(
    *,
    imports: Any,
    keypoints: list[list[float]],
    matrix: Any,
    output_size: tuple[int, int],
    perspective: float,
) -> list[list[float]]:
    """按 affine 矩阵同步变换 keypoints，并更新越界点可见性。"""

    if not keypoints:
        return keypoints
    output_width, output_height = float(output_size[0]), float(output_size[1])
    transformed_keypoints: list[list[float]] = []
    for object_keypoints in keypoints:
        keypoint_count = len(object_keypoints) // 3
        if keypoint_count <= 0:
            transformed_keypoints.append([])
            continue
        points = imports.np.ones((keypoint_count, 3), dtype=imports.np.float32)
        for keypoint_index in range(keypoint_count):
            base_index = keypoint_index * 3
            points[keypoint_index, 0] = float(object_keypoints[base_index])
            points[keypoint_index, 1] = float(object_keypoints[base_index + 1])
        transformed = _transform_yolov8_points(
            imports=imports,
            points=points,
            matrix=matrix,
            perspective=perspective,
        )
        flattened: list[float] = []
        for keypoint_index in range(keypoint_count):
            base_index = keypoint_index * 3
            x_value = float(transformed[keypoint_index, 0])
            y_value = float(transformed[keypoint_index, 1])
            visibility = float(object_keypoints[base_index + 2])
            if x_value < 0.0 or y_value < 0.0 or x_value > output_width or y_value > output_height:
                visibility = 0.0
            flattened.extend([x_value, y_value, visibility])
        transformed_keypoints.append(flattened)
    return transformed_keypoints


def transform_yolov8_obb_boxes(
    *,
    imports: Any,
    boxes_xywhr: list[list[float]],
    matrix: Any,
    output_size: tuple[int, int],
    perspective: float,
) -> tuple[list[list[float]], list[int]]:
    """按 affine 矩阵同步变换 OBB，并返回保留的原始索引。"""

    if not boxes_xywhr:
        return [], []
    output_width, output_height = int(output_size[0]), int(output_size[1])
    transformed_boxes: list[list[float]] = []
    kept_indices: list[int] = []
    for box_index, box in enumerate(boxes_xywhr):
        corners = build_yolov8_obb_corners(imports=imports, box_xywhr=box)
        transformed_corners = _transform_yolov8_points(
            imports=imports,
            points=corners,
            matrix=matrix,
            perspective=perspective,
        )
        transformed_rbox = _min_area_rect_to_yolov8_xywhr(
            imports=imports,
            points=transformed_corners[:, :2],
            output_size=(output_width, output_height),
        )
        if transformed_rbox is None:
            continue
        transformed_boxes.append(transformed_rbox)
        kept_indices.append(box_index)
    return transformed_boxes, kept_indices


def build_yolov8_obb_corners(*, imports: Any, box_xywhr: list[float]) -> Any:
    """把单个 ``xywhr`` 旋转框转换为四角点齐次坐标。"""

    cx, cy, width, height, angle = [float(value) for value in box_xywhr]
    cos_value = math.cos(angle)
    sin_value = math.sin(angle)
    half_width = width / 2.0
    half_height = height / 2.0
    width_vector = imports.np.array([cos_value * half_width, sin_value * half_width])
    height_vector = imports.np.array([-sin_value * half_height, cos_value * half_height])
    center = imports.np.array([cx, cy])
    points = imports.np.stack(
        [
            center + width_vector + height_vector,
            center + width_vector - height_vector,
            center - width_vector - height_vector,
            center - width_vector + height_vector,
        ],
        axis=0,
    ).astype(imports.np.float32)
    ones = imports.np.ones((4, 1), dtype=imports.np.float32)
    return imports.np.concatenate([points, ones], axis=1)


def resolve_yolov8_pose_flip_indices(
    *,
    keypoint_count: int,
    keypoint_flip_indices: tuple[int, ...] | None,
) -> tuple[int, ...] | None:
    """解析 YOLOv8 pose 水平翻转使用的 keypoint 左右交换索引。"""

    if keypoint_flip_indices is not None:
        if len(keypoint_flip_indices) != keypoint_count:
            return None
        return keypoint_flip_indices
    if keypoint_count == 17:
        return (0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15)
    return None


def select_yolov8_items_by_indices(items: list[Any], indices: list[int]) -> list[Any]:
    """按保留索引同步筛选标注列表。"""

    return [items[index] for index in indices if index < len(items)]


def normalize_yolov8_obb_angle(angle: float) -> float:
    """把 OBB angle 规整到以 pi 为周期的半开区间。"""

    return ((float(angle) + math.pi / 2.0) % math.pi) - math.pi / 2.0


def _clamp_probability(value: float) -> float:
    """把概率限制到 0 到 1。"""

    return max(0.0, min(float(value), 1.0))


def _read_float_option(
    options: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    """读取训练增强浮点参数。"""

    try:
        return float(options.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _read_bool_option(
    options: dict[str, object],
    key: str,
    *,
    default: bool,
) -> bool:
    """读取训练增强布尔参数。"""

    value = options.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _read_float_pair_option(
    options: dict[str, object],
    key: str,
    *,
    default: tuple[float, float],
) -> tuple[float, float]:
    """读取训练增强二元浮点参数。"""

    value = options.get(key, default)
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) == 2:
            try:
                parsed = (float(parts[0]), float(parts[1]))
            except ValueError:
                return default
            return _normalize_float_pair(parsed, default=default)
        return default
    if not isinstance(value, list | tuple) or len(value) != 2:
        return default
    try:
        parsed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return default
    return _normalize_float_pair(parsed, default=default)


def _normalize_float_pair(
    value: tuple[float, float],
    *,
    default: tuple[float, float],
) -> tuple[float, float]:
    """规整二元浮点范围。"""

    left, right = float(value[0]), float(value[1])
    if left <= 0.0 or right <= 0.0:
        return default
    return (min(left, right), max(left, right))


def _parse_keypoint_flip_indices(value: object) -> tuple[int, ...] | None:
    """解析用户传入的 keypoint flip index。"""

    if value is None:
        return None
    if not isinstance(value, list | tuple):
        return None
    parsed: list[int] = []
    for item in value:
        try:
            parsed.append(int(item))
        except (TypeError, ValueError):
            return None
    return tuple(parsed)


def _transform_yolov8_points(
    *,
    imports: Any,
    points: Any,
    matrix: Any,
    perspective: float,
) -> Any:
    """使用 3x3 矩阵变换齐次坐标点。"""

    transformed = points @ matrix.T
    if perspective > 0.0:
        denominator = imports.np.clip(transformed[:, 2:3], 1e-6, None)
        transformed[:, :2] = transformed[:, :2] / denominator
    return transformed


def _clip_yolov8_box_xyxy(
    *,
    box_xyxy: list[float] | tuple[float, float, float, float],
    output_size: tuple[int, int],
) -> list[float] | None:
    """把 bbox 裁剪到输出图像范围。"""

    output_width, output_height = float(output_size[0]), float(output_size[1])
    x1 = max(0.0, min(float(box_xyxy[0]), output_width))
    y1 = max(0.0, min(float(box_xyxy[1]), output_height))
    x2 = max(0.0, min(float(box_xyxy[2]), output_width))
    y2 = max(0.0, min(float(box_xyxy[3]), output_height))
    if x2 - x1 <= 2.0 or y2 - y1 <= 2.0:
        return None
    return [x1, y1, x2, y2]


def _is_yolov8_box_candidate(
    *,
    original_box: list[float] | tuple[float, float, float, float],
    transformed_box: list[float],
    area_threshold: float,
) -> bool:
    """按 Ultralytics box candidate 规则过滤退化 bbox。"""

    original_width = max(1e-6, float(original_box[2]) - float(original_box[0]))
    original_height = max(1e-6, float(original_box[3]) - float(original_box[1]))
    transformed_width = max(0.0, transformed_box[2] - transformed_box[0])
    transformed_height = max(0.0, transformed_box[3] - transformed_box[1])
    if transformed_width <= 2.0 or transformed_height <= 2.0:
        return False
    aspect_ratio = max(
        transformed_width / max(transformed_height, 1e-6),
        transformed_height / max(transformed_width, 1e-6),
    )
    area_ratio = (
        transformed_width * transformed_height
        / max(original_width * original_height, 1e-6)
    )
    return aspect_ratio < 100.0 and area_ratio > float(area_threshold)


def _min_area_rect_to_yolov8_xywhr(
    *,
    imports: Any,
    points: Any,
    output_size: tuple[int, int],
) -> list[float] | None:
    """把变换后的四角点转换为 YOLOv8 OBB ``xywhr``。"""

    output_width, output_height = float(output_size[0]), float(output_size[1])
    clipped_points = points.astype(imports.np.float32).copy()
    clipped_points[:, 0] = imports.np.clip(clipped_points[:, 0], 0.0, output_width)
    clipped_points[:, 1] = imports.np.clip(clipped_points[:, 1], 0.0, output_height)
    rect = imports.cv2.minAreaRect(clipped_points)
    (center_x, center_y), (width, height), angle_degrees = rect
    if width <= 2.0 or height <= 2.0:
        return None
    if center_x < 0.0 or center_y < 0.0 or center_x > output_width or center_y > output_height:
        return None
    if width < height:
        width, height = height, width
        angle_degrees += 90.0
    return [
        float(center_x),
        float(center_y),
        float(width),
        float(height),
        normalize_yolov8_obb_angle(math.radians(float(angle_degrees))),
    ]


__all__ = [
    "YoloV8TaskAugmentationOptions",
    "apply_yolov8_random_hsv",
    "apply_yolov8_random_affine",
    "blend_yolov8_mixup_images",
    "build_yolov8_boxes_from_masks",
    "build_yolov8_obb_corners",
    "build_yolov8_random_affine_matrix",
    "build_yolov8_task_augmentation_options",
    "flip_yolov8_image_horizontally",
    "normalize_yolov8_obb_angle",
    "resolve_yolov8_pose_flip_indices",
    "resolve_yolov8_task_augmentation_for_epoch",
    "resolve_yolov8_task_batch_input_size",
    "resize_yolov8_image_to_canvas",
    "select_yolov8_items_by_indices",
    "should_apply_yolov8_horizontal_flip",
    "should_apply_yolov8_random_affine",
    "transform_yolov8_boxes_xyxy",
    "transform_yolov8_keypoints",
    "transform_yolov8_obb_boxes",
    "warp_yolov8_masks",
]
