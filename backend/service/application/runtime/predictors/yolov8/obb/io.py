"""YOLOv8 OBB runtime 输入图片和预处理工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.runtime.predictors.yolov8.segmentation.io import (
    load_yolov8_segmentation_prediction_image,
    preprocess_yolov8_segmentation_image,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def load_yolov8_obb_prediction_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: Any,
) -> Any:
    """按 storage 或 memory 模式加载本次 OBB 推理输入图片。"""

    return load_yolov8_segmentation_prediction_image(
        cv2_module=cv2_module,
        np_module=np_module,
        dataset_storage=dataset_storage,
        request=request,
    )


def preprocess_yolov8_obb_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """按 YOLOv8 OBB 推理规则构造输入张量。"""

    return preprocess_yolov8_segmentation_image(
        cv2_module=cv2_module,
        np_module=np_module,
        image=image,
        input_size=input_size,
    )


__all__ = [
    "load_yolov8_obb_prediction_image",
    "preprocess_yolov8_obb_image",
]
