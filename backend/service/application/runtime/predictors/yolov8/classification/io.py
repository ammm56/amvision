"""YOLOv8 classification runtime 输入图片和预处理工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.runtime.predictors.yolov8.detection.io import (
    load_yolov8_detection_prediction_image,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def load_yolov8_classification_prediction_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: Any,
) -> Any:
    """按 storage 或 memory 模式加载本次 classification 推理输入图片。"""

    return load_yolov8_detection_prediction_image(
        cv2_module=cv2_module,
        np_module=np_module,
        dataset_storage=dataset_storage,
        request=request,
    )


def preprocess_yolov8_classification_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> Any:
    """按 YOLOv8 classification 推理规则构造输入张量。"""

    target_height, target_width = input_size
    resized_image = cv2_module.resize(
        image,
        (int(target_width), int(target_height)),
        interpolation=cv2_module.INTER_LINEAR,
    )
    tensor = resized_image[:, :, ::-1].transpose(2, 0, 1)
    tensor = np_module.ascontiguousarray(tensor, dtype=np_module.float32)
    return tensor / 255.0


__all__ = [
    "load_yolov8_classification_prediction_image",
    "preprocess_yolov8_classification_image",
]
