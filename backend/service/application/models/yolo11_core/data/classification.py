"""YOLO11 classification 训练和评估 batch 编码。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.data import (
    YoloClassificationAugmentationOptions,
    apply_yolo_classification_augmentation,
)
from backend.service.application.models.yolo_core_common.data.tensor_transfer import (
    move_yolo_tensor_to_training_device,
)


@dataclass(frozen=True)
class Yolo11ClassificationTrainingBatch:
    """描述 YOLO11 classification 训练或评估使用的 batch。"""

    images: Any
    targets: Any


def build_yolo11_classification_training_batch(
    *,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
    augmentation_options: YoloClassificationAugmentationOptions | None = None,
) -> Yolo11ClassificationTrainingBatch | None:
    """把样本列表编码为 YOLO11 classification 训练 batch。"""

    if not samples:
        return None

    image_tensors: list[Any] = []
    target_indexes: list[int] = []
    for sample in samples:
        image_array = load_yolo11_classification_image(
            image_path=str(sample.image_path),
            input_size=input_size,
            cv2_module=imports.cv2,
            np_module=imports.np,
            augmentation_options=augmentation_options,
        )
        image_tensors.append(imports.torch.from_numpy(image_array).float())
        target_indexes.append(int(sample.class_id))

    if not image_tensors:
        return None
    return Yolo11ClassificationTrainingBatch(
        images=move_yolo_tensor_to_training_device(
            imports.torch.stack(image_tensors, dim=0),
            device=device,
            runtime_precision=precision,
        ),
        targets=imports.torch.tensor(
            target_indexes,
            dtype=imports.torch.long,
            device=device,
        ),
    )


def load_yolo11_classification_image(
    *,
    image_path: str,
    input_size: tuple[int, int],
    cv2_module: Any,
    np_module: Any,
    augmentation_options: YoloClassificationAugmentationOptions | None = None,
) -> Any:
    """读取并缩放 YOLO11 classification 图片。"""

    image = cv2_module.imread(image_path)
    if image is None:
        raise InvalidRequestError(
            f"无法读取 YOLO11 classification 训练图片: {image_path}"
        )
    image = apply_yolo_classification_augmentation(
        image=image,
        options=augmentation_options,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    resized = cv2_module.resize(
        image,
        (int(input_size[1]), int(input_size[0])),
        interpolation=cv2_module.INTER_LINEAR,
    )
    return resized[:, :, ::-1].transpose(2, 0, 1).astype(np_module.float32) / 255.0


__all__ = [
    "Yolo11ClassificationTrainingBatch",
    "build_yolo11_classification_training_batch",
    "load_yolo11_classification_image",
]
