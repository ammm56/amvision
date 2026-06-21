"""YOLO26 OBB runtime 输入图片和预处理工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.runtime.predictors.yolo_runtime_io import (
    load_yolo_runtime_prediction_image,
    preprocess_yolo_runtime_letterbox_image,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def load_yolo26_obb_prediction_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: Any,
) -> Any:
    """按 storage 或 memory 模式加载本次 OBB 推理输入图片。"""

    return load_yolo_runtime_prediction_image(
        cv2_module=cv2_module,
        np_module=np_module,
        dataset_storage=dataset_storage,
        request=request,
    )


def preprocess_yolo26_obb_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """按 YOLO26 OBB 推理规则构造输入张量。"""

    return preprocess_yolo_runtime_letterbox_image(
        cv2_module=cv2_module,
        np_module=np_module,
        image=image,
        input_size=input_size,
    )


__all__ = [
    "load_yolo26_obb_prediction_image",
    "preprocess_yolo26_obb_image",
]
