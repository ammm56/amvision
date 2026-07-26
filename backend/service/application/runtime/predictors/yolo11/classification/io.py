"""YOLO11 classification runtime 输入图片和预处理工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.data import (
    normalize_yolo_classification_image,
    prepare_yolo_classification_image,
)
from backend.service.application.runtime.predictors.yolo11.segmentation.io import (
    load_yolo11_segmentation_prediction_image,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def load_yolo11_classification_prediction_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: Any,
) -> Any:
    """按 storage 或 memory 模式加载本次 classification 推理输入图片。"""

    return load_yolo11_segmentation_prediction_image(
        cv2_module=cv2_module,
        np_module=np_module,
        dataset_storage=dataset_storage,
        request=request,
    )


def preprocess_yolo11_classification_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> Any:
    """按 YOLO11 classification 推理规则构造输入张量。"""

    resized_image = prepare_yolo_classification_image(
        image=image,
        input_size=input_size,
        training=False,
        cv2_module=cv2_module,
    )
    return normalize_yolo_classification_image(
        image=resized_image,
        options=None,
        np_module=np_module,
    )


__all__ = [
    "load_yolo11_classification_prediction_image",
    "preprocess_yolo11_classification_image",
]
