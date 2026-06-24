"""OpenCV shared 图片读写和裁剪输出工具。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from backend.nodes.runtime_support import (
    build_runtime_image_object_key,
    load_image_bytes,
    register_image_bytes,
    write_image_bytes,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.validators import normalize_optional_object_key

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
    image_payload, image_bytes = load_image_bytes(request, input_name=input_name)
    image_buffer = np_module.frombuffer(image_bytes, dtype=np_module.uint8)
    image_matrix = cv2_module.imdecode(
        image_buffer,
        cv2_module.IMREAD_COLOR if imdecode_flags is None else imdecode_flags,
    )
    if image_matrix is None:
        error_details = {
            "node_id": getattr(request, "node_id", ""),
            "transport_kind": image_payload.get("transport_kind"),
            "media_type": image_payload.get("media_type"),
        }
        source_object_key = image_payload.get("object_key")
        if isinstance(source_object_key, str) and source_object_key:
            error_details["object_key"] = source_object_key
        raise InvalidRequestError(
            "OpenCV 无法读取输入图片",
            details=error_details,
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
            content=content,
            object_key=normalized_object_key,
            variant_name=variant_name,
            output_extension=output_extension,
            width=width,
            height=height,
            media_type=media_type,
        )
    return register_image_bytes(
        request,
        content=content,
        media_type=media_type,
        width=width,
        height=height,
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
    return encoded_image.tobytes()

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
