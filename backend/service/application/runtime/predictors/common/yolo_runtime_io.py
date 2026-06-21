"""YOLO runtime 输入图片和预处理通用工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.targets.runtime_target import resolve_local_file_path
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def load_yolo_runtime_prediction_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: Any,
) -> Any:
    """按 storage 或 memory 模式加载本次推理输入图片。"""

    has_input_uri = isinstance(request.input_uri, str) and bool(request.input_uri.strip())
    has_input_image_bytes = isinstance(request.input_image_bytes, bytes) and bool(request.input_image_bytes)
    if has_input_uri == has_input_image_bytes:
        raise InvalidRequestError(
            "推理请求必须且只能提供 input_uri 或 input_image_bytes 其中一个",
            details={
                "provided_input_uri": bool(has_input_uri),
                "provided_input_image_bytes": bool(has_input_image_bytes),
            },
        )
    if has_input_uri:
        image_path = resolve_local_file_path(
            dataset_storage=dataset_storage,
            storage_uri=request.input_uri or "",
            field_name="input_uri",
        )
        image = cv2_module.imread(str(image_path))
        if image is None:
            raise InvalidRequestError(
                "input_uri 指向的图片无法读取",
                details={"input_uri": request.input_uri},
            )
        return image

    buffer = np_module.frombuffer(request.input_image_bytes or b"", dtype=np_module.uint8)
    image = cv2_module.imdecode(buffer, cv2_module.IMREAD_COLOR)
    if image is None:
        raise InvalidRequestError(
            "input_image_bytes 不是可读取的图片内容",
            details={"field": "input_image_bytes"},
        )
    return image


def preprocess_yolo_runtime_letterbox_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """按 YOLO letterbox 规则构造输入张量。"""

    target_height, target_width = input_size
    source_height, source_width = int(image.shape[0]), int(image.shape[1])
    resize_ratio = min(target_height / source_height, target_width / source_width)
    resized_width = max(1, int(round(source_width * resize_ratio)))
    resized_height = max(1, int(round(source_height * resize_ratio)))
    resized_image = cv2_module.resize(
        image,
        (resized_width, resized_height),
        interpolation=cv2_module.INTER_LINEAR,
    )
    padded_image = np_module.full((target_height, target_width, 3), 114, dtype=np_module.uint8)
    padded_image[:resized_height, :resized_width] = resized_image
    tensor = padded_image[:, :, ::-1].transpose(2, 0, 1)
    return np_module.ascontiguousarray(tensor, dtype=np_module.float32), float(resize_ratio)


__all__ = [
    "load_yolo_runtime_prediction_image",
    "preprocess_yolo_runtime_letterbox_image",
]
