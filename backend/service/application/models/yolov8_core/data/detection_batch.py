"""YOLOv8 detection batch 编码。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolov8_core.data.detection_augmentation import (
    prepare_yolov8_detection_sample_with_augmentation,
    prepare_yolov8_detection_sample_without_augmentation,
)
from backend.service.application.models.yolov8_core.data.detection_types import (
    YoloV8DetectionAugmentationOptions,
    YoloV8DetectionPreparedTarget,
    YoloV8DetectionTrainingSample,
)


def build_yolov8_detection_training_batch(
    *,
    imports: Any,
    samples: list[YoloV8DetectionTrainingSample],
    input_size: tuple[int, int],
    device: str,
    runtime_precision: str,
    augment_training: bool = False,
    available_samples: tuple[YoloV8DetectionTrainingSample, ...] | None = None,
    augmentation_options: YoloV8DetectionAugmentationOptions | None = None,
) -> tuple[Any, tuple[YoloV8DetectionPreparedTarget, ...]]:
    """把 YOLOv8 detection 样本拼成训练或 validation batch。"""

    np_module = imports.np
    torch = imports.torch
    image_tensors: list[Any] = []
    prepared_targets: list[YoloV8DetectionPreparedTarget] = []
    resolved_available_samples = (
        available_samples
        if available_samples is not None and len(available_samples) > 0
        else tuple(samples)
    )
    resolved_augmentation_options = augmentation_options or YoloV8DetectionAugmentationOptions(
        flip_prob=0.0,
        hsv_prob=0.0,
        mosaic_prob=0.0,
        mixup_prob=0.0,
        enable_mixup=False,
        degrees=0.0,
        translate=0.0,
        shear=0.0,
        mosaic_scale=(1.0, 1.0),
        mixup_scale=(1.0, 1.0),
    )
    for sample in samples:
        if augment_training:
            prepared_image, resized_boxes, resized_categories = (
                prepare_yolov8_detection_sample_with_augmentation(
                    imports=imports,
                    primary_sample=sample,
                    available_samples=resolved_available_samples,
                    input_size=input_size,
                    augmentation_options=resolved_augmentation_options,
                )
            )
        else:
            prepared_image, resized_boxes, resized_categories = (
                prepare_yolov8_detection_sample_without_augmentation(
                    imports=imports,
                    sample=sample,
                    input_size=input_size,
                )
            )
        rgb_image = imports.cv2.cvtColor(prepared_image, imports.cv2.COLOR_BGR2RGB)
        image_array = rgb_image.astype(np_module.float32) / 255.0
        image_array = np_module.transpose(image_array, (2, 0, 1))
        image_tensors.append(torch.from_numpy(image_array))
        prepared_targets.append(
            YoloV8DetectionPreparedTarget(
                image_id=sample.image_id,
                image_width=input_size[1] if augment_training else sample.image_width,
                image_height=input_size[0] if augment_training else sample.image_height,
                boxes_xyxy=tuple(resized_boxes),
                category_indexes=tuple(resized_categories),
            )
        )
    images = torch.stack(image_tensors, dim=0).to(device)
    if runtime_precision == "fp16":
        images = images.half()
    return images, tuple(prepared_targets)


__all__ = ["build_yolov8_detection_training_batch"]
