"""YOLOv8 detection batch 编码。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)
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
    """把 YOLOv8 detection CPU batch 搬运到训练设备。"""

    images, prepared_targets = build_yolov8_detection_training_batch_cpu(
        imports=imports,
        samples=samples,
        input_size=input_size,
        augment_training=augment_training,
        available_samples=available_samples,
        augmentation_options=augmentation_options,
    )
    images = move_yolo_tensor_to_training_device(
        images,
        device=device,
        runtime_precision=runtime_precision,
    )
    return images, prepared_targets


def build_yolov8_detection_training_batch_cpu(
    *,
    imports: Any,
    samples: list[YoloV8DetectionTrainingSample],
    input_size: tuple[int, int],
    augment_training: bool = False,
    available_samples: tuple[YoloV8DetectionTrainingSample, ...] | None = None,
    augmentation_options: YoloV8DetectionAugmentationOptions | None = None,
) -> tuple[Any, tuple[YoloV8DetectionPreparedTarget, ...]]:
    """把 YOLOv8 detection 样本拼成 CPU batch，供 DataLoader worker 预取。"""

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
        multi_scale_range=(1.0, 1.0),
        multi_scale_stride=32,
    )
    for sample in samples:
        letterbox_transform = None
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
            (
                prepared_image,
                resized_boxes,
                resized_categories,
                letterbox_transform,
            ) = (
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
                letterbox_transform=letterbox_transform,
            )
        )
    images = torch.stack(image_tensors, dim=0)
    return images, tuple(prepared_targets)


__all__ = [
    "build_yolov8_detection_training_batch",
    "build_yolov8_detection_training_batch_cpu",
]
