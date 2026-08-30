"""OpenCV shared 图片读写和裁剪输出工具。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.nodes.save_locations import (
    SAVE_LOCATION_OBJECT_STORE,
    WorkflowSaveLocation,
    resolve_optional_save_location,
    save_bytes,
)
from backend.nodes.runtime_support import (
    build_storage_image_payload,
    load_image_matrix as load_runtime_image_matrix,
    register_image_matrix,
    register_image_bytes,
    register_typed_image_matrix,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)


class EncodedImageBytes:
    """携带 OpenCV matrix 的懒编码图片对象。

    说明：
    - 大多数节点没有显式 save_location 时会直接输出 memory/raw BGR24，
      不需要先 PNG 编码。
    - 只有确实需要落盘时，bytes(content) 才触发编码。
    """

    def __init__(
        self, *, request: object, image_matrix: Any, extension: str, error_message: str
    ) -> None:
        """保存懒编码所需的最小上下文。"""

        self.request = request
        self.image_matrix = image_matrix
        self.extension = extension
        self.error_message = error_message
        self._encoded_bytes: bytes | None = None

    def __bytes__(self) -> bytes:
        """按需执行 OpenCV 编码并缓存结果。"""

        if self._encoded_bytes is None:
            cv2_module, _ = require_opencv_imports()
            encode_params: list[int] = []
            normalized_extension = self.extension.strip().lower() or ".png"
            if normalized_extension in {".jpg", ".jpeg"}:
                encode_params = [int(cv2_module.IMWRITE_JPEG_QUALITY), 82]
            elif normalized_extension == ".png":
                encode_params = [int(cv2_module.IMWRITE_PNG_COMPRESSION), 1]
            success, encoded_image = cv2_module.imencode(
                normalized_extension,
                self.image_matrix,
                encode_params,
            )
            if success is not True:
                raise ServiceConfigurationError(
                    self.error_message,
                    details={"node_id": getattr(self.request, "node_id", "")},
                )
            self._encoded_bytes = encoded_image.tobytes()
        return self._encoded_bytes


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
        copy_raw=False,
    )
    resolved_source_object_key = image_payload.get("object_key")
    return (
        image_payload,
        resolved_source_object_key
        if isinstance(resolved_source_object_key, str) and resolved_source_object_key
        else None,
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
    save_location: str | None = None,
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

    resolved_save_location = resolve_optional_save_location(save_location, scope="file")
    if resolved_save_location is not None:
        encoded_content = bytes(content)
        saved_file = save_bytes(
            request,
            save_location=resolved_save_location,
            content=encoded_content,
        )
        if saved_file.kind == SAVE_LOCATION_OBJECT_STORE:
            image_payload = build_storage_image_payload(
                object_key=str(saved_file.object_key or ""),
                source_payload=source_payload,
                width=width,
                height=height,
                media_type=media_type,
            )
        else:
            image_matrix = getattr(content, "image_matrix", None)
            image_payload = (
                register_image_matrix(request, image_matrix=image_matrix)
                if image_matrix is not None
                else register_image_bytes(
                    request,
                    content=encoded_content,
                    media_type=media_type,
                    width=width,
                    height=height,
                )
            )
        image_payload["saved_output"] = saved_file.to_payload()
        return image_payload
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
    save_location: str | None,
    variant_name: str,
    output_extension: str = ".png",
    media_type: str = "image/png",
    error_message: str = "OpenCV 节点无法编码输出图片",
) -> dict[str, object]:
    """按输出模式返回绘制后的图片，memory/raw 模式不做 PNG 编码。"""

    if not isinstance(save_location, str) or not save_location.strip():
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
        save_location=save_location,
        variant_name=variant_name,
        output_extension=output_extension,
        width=int(image_matrix.shape[1]),
        height=int(image_matrix.shape[0]),
        media_type=media_type,
    )


def build_typed_output_image_matrix_payload(
    request: object,
    *,
    image_matrix: Any,
) -> dict[str, object]:
    """注册保留 dtype 的执行期图片，不把 typed matrix 隐式降为 uint8。"""

    return register_typed_image_matrix(request, image_matrix=image_matrix)


def encode_png_image_bytes(
    request: object,
    *,
    image_matrix: Any,
    error_message: str,
) -> EncodedImageBytes:
    """返回按需编码为 PNG 的图片对象。"""

    return EncodedImageBytes(
        request=request,
        image_matrix=image_matrix,
        extension=".png",
        error_message=error_message,
    )


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


def build_image_crop_batch_timestamp() -> str:
    """生成一次图片批量输出共用的本地时间戳。"""

    return datetime.now().strftime("%Y%m%d%H%M%S")


def build_image_crop_output_name(*, batch_timestamp: str, item_index: int) -> str:
    """生成统一的批量图片文件名。"""

    if len(batch_timestamp) != 14 or not batch_timestamp.isdigit():
        raise InvalidRequestError("图片批量输出时间戳格式无效")
    if item_index < 1:
        raise InvalidRequestError("图片批量输出序号必须大于 0")
    return f"image-crop-{batch_timestamp}-{item_index:03d}.png"


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


def build_persisted_output_image_matrix_payload(
    request: object,
    *,
    source_payload: dict[str, object],
    image_matrix: Any,
    save_location: WorkflowSaveLocation,
    output_name: str,
    keep_raw_memory: bool,
    media_type: str = "image/png",
    error_message: str = "OpenCV 节点无法编码输出图片",
) -> dict[str, object]:
    """保存图片，并按节点用途返回 storage 或 memory image-ref。

    参数：
    - request：当前节点执行请求。
    - source_payload：源图片 payload。
    - image_matrix：待保存的 OpenCV matrix。
    - save_location：已解析的保存位置。
    - output_name：输出文件名。
    - keep_raw_memory：是否保留 raw matrix 供后续节点高性能消费。

    返回：
    - dict[str, object]：带 saved_output 的 image-ref payload。
    """

    encoded_image = bytes(
        encode_png_image_bytes(
            request,
            image_matrix=image_matrix,
            error_message=error_message,
        )
    )
    output_file = save_bytes(
        request,
        save_location=save_location,
        file_name=output_name,
        content=encoded_image,
    )
    if output_file.kind == SAVE_LOCATION_OBJECT_STORE and not keep_raw_memory:
        image_payload = build_storage_image_payload(
            object_key=str(output_file.object_key or ""),
            source_payload=source_payload,
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
            media_type=media_type,
        )
    elif keep_raw_memory:
        image_payload = register_image_matrix(
            request,
            image_matrix=image_matrix,
        )
    else:
        image_payload = register_image_bytes(
            request,
            content=encoded_image,
            media_type=media_type,
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
        )
    image_payload["saved_output"] = output_file.to_payload()
    return image_payload
