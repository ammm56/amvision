"""OpenCV shared 图片读写和裁剪输出工具。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from backend.nodes.runtime_support import (
    build_runtime_image_object_key,
    load_image_matrix as load_runtime_image_matrix,
    register_image_matrix,
    register_image_bytes,
    write_image_bytes,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.validators import normalize_optional_object_key


class EncodedImageBytes(bytes):
    """携带原始 OpenCV matrix 的编码图片 bytes。

    说明：
    - 对旧代码表现为普通 bytes。
    - 对 build_output_image_payload，未指定 object_key 时可跳过编码 bytes，
      直接把 image_matrix 注册为 raw BGR24 memory image-ref。
    """

    image_matrix: Any

    def __new__(cls, value: bytes, image_matrix: Any):
        """创建 bytes 兼容对象。"""

        current = super().__new__(cls, value)
        current.image_matrix = image_matrix
        return current


def load_image_matrix(
    request: object,
    *,
    input_name: str = "image",
    imdecode_flags: int | None = None,
) -> tuple[dict[str, object], str | None, Any]:
    """按多来源 image-ref 规则读取图片输入，并解码为 OpenCV matrix。

    参数：
    - request：当前节点执行请求。
    - input_name：输入端口名称。
    - imdecode_flags：OpenCV 解码标志；未提供时使用 IMREAD_COLOR。

    返回：
    - tuple[dict[str, object], str | None, Any]：规范化图片 payload、可选 source_object_key 和解码后的图片矩阵。
    """

    cv2_module, np_module = require_opencv_imports()
    image_payload, image_matrix = load_runtime_image_matrix(
        request,
        input_name=input_name,
        cv2_module=cv2_module,
        np_module=np_module,
        imdecode_flags=imdecode_flags,
        copy_raw=True,
    )
    resolved_source_object_key = image_payload.get("object_key")
    return (
        image_payload,
        resolved_source_object_key if isinstance(resolved_source_object_key, str) and resolved_source_object_key else None,
        image_matrix,
    )

def build_output_image_payload(
    request: object,
    *,
    source_payload: dict[str, object],
    content: bytes,
    width: int,
    height: int,
    media_type: str,
    variant_name: str,
    output_extension: str,
    object_key: str | None = None,
) -> dict[str, object]:
    """根据可选 object_key 选择 storage 或 memory 模式输出图片。

    参数：
    - request：当前节点执行请求。
    - source_payload：源图片 payload。
    - content：编码后的图片字节。
    - width：输出图片宽度。
    - height：输出图片高度。
    - media_type：输出图片媒体类型。
    - variant_name：默认输出变体名。
    - output_extension：默认输出扩展名。
    - object_key：显式输出 object key；未提供时返回 memory image-ref。

    返回：
    - dict[str, object]：输出图片 payload。
    """

    normalized_object_key = normalize_optional_object_key(object_key)
    if normalized_object_key is not None:
        return write_image_bytes(
            request,
            source_payload=source_payload,
            content=bytes(content),
            object_key=normalized_object_key,
            variant_name=variant_name,
            output_extension=output_extension,
            width=width,
            height=height,
            media_type=media_type,
        )
    image_matrix = getattr(content, "image_matrix", None)
    if image_matrix is not None:
        return register_image_matrix(request, image_matrix=image_matrix)
    return register_image_bytes(
        request,
        content=bytes(content),
        media_type=media_type,
        width=width,
        height=height,
    )

def build_output_image_matrix_payload(
    request: object,
    *,
    source_payload: dict[str, object],
    image_matrix: Any,
    object_key: str | None,
    variant_name: str,
    output_extension: str = ".png",
    media_type: str = "image/png",
    error_message: str = "OpenCV 节点无法编码输出图片",
) -> dict[str, object]:
    """按输出模式返回绘制后的图片，memory/raw 模式不做 PNG 编码。"""

    normalized_object_key = normalize_optional_object_key(object_key)
    if normalized_object_key is None:
        return register_image_matrix(request, image_matrix=image_matrix)
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=image_matrix,
        error_message=error_message,
    )
    return build_output_image_payload(
        request,
        source_payload=source_payload,
        content=encoded_image,
        object_key=normalized_object_key,
        variant_name=variant_name,
        output_extension=output_extension,
        width=int(image_matrix.shape[1]),
        height=int(image_matrix.shape[0]),
        media_type=media_type,
    )

def encode_png_image_bytes(
    request: object,
    *,
    image_matrix: Any,
    error_message: str,
) -> bytes:
    """把 OpenCV matrix 编码为 PNG 字节。"""

    cv2_module, _ = require_opencv_imports()
    success, encoded_image = cv2_module.imencode(".png", image_matrix)
    if success is not True:
        raise ServiceConfigurationError(
            error_message,
            details={"node_id": getattr(request, "node_id", "")},
        )
    return EncodedImageBytes(encoded_image.tobytes(), image_matrix)

def require_dataset_path(request: object, object_key: str):
    """把 object key 解析为本地绝对路径。

    参数：
    - request：当前节点执行请求。
    - object_key：图片 object key。

    返回：
    - Path：对应的本地绝对路径。
    """

    from backend.nodes.runtime_support import require_dataset_storage

    return require_dataset_storage(request).resolve(object_key)

def normalize_optional_output_dir(value: object) -> str | None:
    """规范化可选裁剪输出目录。

    参数：
    - value：原始输出目录。

    返回：
    - str | None：规范化后的输出目录。
    """

    if not isinstance(value, str) or not value.strip():
        return None
    normalized_value = value.strip().replace("\\", "/").rstrip("/")
    if ".." in normalized_value.split("/"):
        raise InvalidRequestError("output_dir 不能包含父目录引用")
    return normalized_value

def clip_bbox(
    *,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    image_width: int,
    image_height: int,
    box_padding: int,
) -> tuple[int, int, int, int] | None:
    """把 bbox 限制在图片边界内，并应用 padding。

    参数：
    - x1：左上角 x。
    - y1：左上角 y。
    - x2：右下角 x。
    - y2：右下角 y。
    - image_width：图片宽度。
    - image_height：图片高度。
    - box_padding：padding 像素。

    返回：
    - tuple[int, int, int, int] | None：裁剪后的 bbox；无效时返回 None。
    """

    clipped_x1 = max(0, x1 - box_padding)
    clipped_y1 = max(0, y1 - box_padding)
    clipped_x2 = min(image_width, x2 + box_padding)
    clipped_y2 = min(image_height, y2 + box_padding)
    if clipped_x2 <= clipped_x1 or clipped_y2 <= clipped_y1:
        return None
    return clipped_x1, clipped_y1, clipped_x2, clipped_y2

def build_crop_object_key(
    request: object,
    *,
    source_object_key: str | None,
    output_dir: str | None,
    detection_index: int,
) -> str:
    """为单个裁剪图生成输出 object key。

    参数：
    - request：当前节点执行请求。
    - source_object_key：源图片 object key。
    - output_dir：可选输出目录。
    - detection_index：当前 detection 序号。

    返回：
    - str：裁剪图 object key。
    """

    normalized_source_object_key = source_object_key.strip() if isinstance(source_object_key, str) else ""
    if output_dir is not None:
        source_stem = PurePosixPath(normalized_source_object_key).stem or "image"
        return f"{output_dir}/{source_stem}-crop-{detection_index:03d}.png"
    return build_runtime_image_object_key(
        request,
        source_object_key=normalized_source_object_key or "image.png",
        variant_name=f"crop-{detection_index:03d}",
        output_extension=".png",
    )
