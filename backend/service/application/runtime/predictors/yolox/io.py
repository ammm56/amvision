"""YOLOX runtime 输入图片和预处理工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.images.image_matrix import decode_image_bytes_to_matrix
from backend.service.application.runtime.targets.runtime_target import resolve_local_file_path
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def load_yolox_prediction_image(
    *,
    cv2_module: Any,
    np_module: Any,
    dataset_storage: LocalDatasetStorage,
    request: Any,
) -> Any:
    """按 storage 或 memory 模式加载本次推理输入图片。

    参数：
    - cv2_module：OpenCV 模块。
    - np_module：NumPy 模块。
    - dataset_storage：本地文件存储服务。
    - request：推理请求。

    返回：
    - Any：OpenCV 读取后的图片矩阵。
    """

    has_input_uri = isinstance(request.input_uri, str) and request.input_uri.strip()
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

    return decode_image_bytes_to_matrix(
        cv2_module=cv2_module,
        np_module=np_module,
        image_bytes=request.input_image_bytes or b"",
        image_payload=getattr(request, "input_image_payload", None),
        error_message="input_image_bytes 不是可读取的图片内容",
    )


def preprocess_yolox_image(
    *,
    cv2_module: Any,
    np_module: Any,
    image: Any,
    input_size: tuple[int, int],
) -> tuple[Any, float]:
    """按 YOLOX 预处理规则构造输入张量。"""

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
