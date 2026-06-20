"""YOLO26 classification 训练和评估 batch 编码。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Yolo26ClassificationTrainingBatch:
    """描述 YOLO26 classification 训练或评估使用的 batch。"""

    images: Any
    targets: Any


def build_yolo26_classification_training_batch(
    *,
    samples: Sequence[Any],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
) -> Yolo26ClassificationTrainingBatch | None:
    """把样本列表编码为 YOLO26 classification 训练 batch。"""

    if not samples:
        return None

    image_tensors: list[Any] = []
    target_indexes: list[int] = []
    for sample in samples:
        image_array = load_yolo26_classification_image(
            image_path=str(sample.image_path),
            input_size=input_size,
            cv2_module=imports.cv2,
            np_module=imports.np,
        )
        image_tensor = imports.torch.from_numpy(image_array).to(device).float()
        if precision == "fp16":
            image_tensor = image_tensor.half()
        image_tensors.append(image_tensor)
        target_indexes.append(int(sample.class_id))

    if not image_tensors:
        return None
    return Yolo26ClassificationTrainingBatch(
        images=imports.torch.stack(image_tensors, dim=0),
        targets=imports.torch.tensor(
            target_indexes,
            dtype=imports.torch.long,
            device=device,
        ),
    )


def load_yolo26_classification_image(
    *,
    image_path: str,
    input_size: tuple[int, int],
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """读取并缩放 YOLO26 classification 图片。"""

    image = cv2_module.imread(image_path)
    if image is None:
        raise InvalidRequestError(
            f"无法读取 YOLO26 classification 训练图片: {image_path}"
        )
    resized = cv2_module.resize(
        image,
        (int(input_size[1]), int(input_size[0])),
        interpolation=cv2_module.INTER_LINEAR,
    )
    return resized[:, :, ::-1].transpose(2, 0, 1).astype(np_module.float32) / 255.0


__all__ = [
    "Yolo26ClassificationTrainingBatch",
    "build_yolo26_classification_training_batch",
    "load_yolo26_classification_image",
]

