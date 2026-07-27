"""RF-DETR runtime 输入图片读取和预处理工具。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from backend.service.application.runtime.support.detection import load_prediction_image
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)

RFDETR_IMAGENET_MEAN: tuple[float, float, float] = (0.485, 0.456, 0.406)
RFDETR_IMAGENET_STD: tuple[float, float, float] = (0.229, 0.224, 0.225)


def load_rfdetr_runtime_input_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: Any,
) -> tuple[Any, float]:
    """读取 RF-DETR runtime 输入图片，并返回解码耗时。"""

    decode_started_at = perf_counter()
    image = load_prediction_image(
        cv2_module=cv2_module,
        np_module=np_module,
        dataset_storage=dataset_storage,
        request=request,
    )
    decode_ms = round((perf_counter() - decode_started_at) * 1000, 3)
    return image, decode_ms


def build_rfdetr_input_array(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """把 BGR 图片整理成 RF-DETR runtime 使用的 ImageNet 归一化 NCHW 输入。"""

    preprocess_started_at = perf_counter()
    input_height, input_width = input_size
    # RF-DETR 参考推理在 resize 前先转换为 float tensor。OpenCV 对 float32
    # 使用同一无 antialias 的 bilinear 语义，可避免 uint8 resize 的量化误差。
    float_image = image.astype(np_module.float32) / 255.0
    resized_image = cv2_module.resize(
        float_image,
        (input_width, input_height),
        interpolation=cv2_module.INTER_LINEAR,
    )
    input_array = resized_image[:, :, ::-1].transpose(2, 0, 1)
    input_array = np_module.expand_dims(input_array, axis=0)
    mean = np_module.asarray(RFDETR_IMAGENET_MEAN, dtype=np_module.float32).reshape(1, 3, 1, 1)
    std = np_module.asarray(RFDETR_IMAGENET_STD, dtype=np_module.float32).reshape(1, 3, 1, 1)
    input_array = (input_array - mean) / std
    preprocess_ms = round((perf_counter() - preprocess_started_at) * 1000, 3)
    return input_array, preprocess_ms
