"""高性能图片数据面 helper。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError


IMAGE_MEDIA_TYPE_RAW = "image/raw"
IMAGE_DTYPE_UINT8 = "uint8"
IMAGE_LAYOUT_HWC = "HWC"
IMAGE_PIXEL_FORMAT_BGR24 = "bgr24"
IMAGE_PIXEL_FORMAT_RGB24 = "rgb24"
IMAGE_PIXEL_FORMAT_GRAY8 = "gray8"


@dataclass(frozen=True)
class ImagePayloadMetadata:
    """描述 image-ref payload 中和图片内存布局相关的字段。"""

    media_type: str
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    width: int | None = None
    height: int | None = None


def normalize_image_payload_metadata(payload: object) -> ImagePayloadMetadata:
    """从 image-ref payload 中读取图片元数据。

    参数：
    - payload：image-ref payload 或空值。

    返回：
    - ImagePayloadMetadata：规范化后的元数据。
    """

    if not isinstance(payload, dict):
        return ImagePayloadMetadata(media_type="")
    media_type = _normalize_optional_text(payload.get("media_type")) or ""
    return ImagePayloadMetadata(
        media_type=media_type,
        shape=_normalize_shape(payload.get("shape")),
        dtype=_normalize_optional_text(payload.get("dtype")),
        layout=_normalize_layout(payload.get("layout")),
        pixel_format=_normalize_pixel_format(payload.get("pixel_format")),
        width=_normalize_optional_dimension(payload.get("width")),
        height=_normalize_optional_dimension(payload.get("height")),
    )


def apply_raw_ref_metadata(
    payload: dict[str, object],
    *,
    shape: tuple[int, ...],
    dtype: str | None,
    layout: str | None,
    pixel_format: str | None,
) -> None:
    """把 BufferRef / FrameRef 上的 raw 元数据同步到 image-ref payload。"""

    if shape:
        payload["shape"] = [int(item) for item in shape]
    else:
        payload.pop("shape", None)
    normalized_dtype = _normalize_optional_text(dtype)
    normalized_layout = _normalize_layout(layout)
    normalized_pixel_format = _normalize_pixel_format(pixel_format)
    if normalized_dtype is None:
        payload.pop("dtype", None)
    else:
        payload["dtype"] = normalized_dtype
    if normalized_layout is None:
        payload.pop("layout", None)
    else:
        payload["layout"] = normalized_layout
    if normalized_pixel_format is None:
        payload.pop("pixel_format", None)
    else:
        payload["pixel_format"] = normalized_pixel_format


def validate_raw_bgr24_bytes(
    *,
    image_bytes: bytes,
    shape: tuple[int, ...],
    dtype: str | None,
    layout: str | None,
    pixel_format: str | None,
) -> None:
    """校验 raw BGR24 字节和元数据是否一致。

    参数：
    - image_bytes：raw 图片 bytes。
    - shape：图片 shape，要求 HWC 三通道。
    - dtype：raw dtype，要求 uint8。
    - layout：raw layout，要求 HWC。
    - pixel_format：像素格式，要求 bgr24。
    """

    normalized_dtype = _normalize_optional_text(dtype)
    normalized_layout = _normalize_layout(layout)
    normalized_pixel_format = _normalize_pixel_format(pixel_format)
    if normalized_dtype != IMAGE_DTYPE_UINT8:
        raise InvalidRequestError(
            "raw BGR24 图片要求 dtype=uint8",
            details={"dtype": dtype},
        )
    if normalized_layout != IMAGE_LAYOUT_HWC:
        raise InvalidRequestError(
            "raw BGR24 图片要求 layout=HWC",
            details={"layout": layout},
        )
    if normalized_pixel_format != IMAGE_PIXEL_FORMAT_BGR24:
        raise InvalidRequestError(
            "raw BGR24 图片要求 pixel_format=bgr24",
            details={"pixel_format": pixel_format},
        )
    if len(shape) != 3 or int(shape[2]) != 3:
        raise InvalidRequestError(
            "raw BGR24 图片要求 shape=[height,width,3]",
            details={"shape": list(shape)},
        )
    expected_size = int(shape[0]) * int(shape[1]) * int(shape[2])
    if len(image_bytes) != expected_size:
        raise InvalidRequestError(
            "raw BGR24 图片 bytes 长度与 shape 不一致",
            details={
                "expected_size": expected_size,
                "actual_size": len(image_bytes),
                "shape": list(shape),
            },
        )


def decode_image_bytes_to_matrix(
    *,
    cv2_module: Any,
    np_module: Any,
    image_bytes: bytes,
    image_payload: object,
    imdecode_flags: int | None = None,
    error_message: str = "输入图片无法读取",
    copy_raw: bool = False,
) -> Any:
    """把 image bytes 转换为 OpenCV matrix。

    raw BGR24 会直接使用 NumPy view 解释内存，不经过 cv2.imdecode；JPEG/PNG/BMP
    等编码图片仍走 OpenCV 解码。
    """

    metadata = normalize_image_payload_metadata(image_payload)
    transport_kind = (
        _normalize_optional_text(image_payload.get("transport_kind"))
        if isinstance(image_payload, dict)
        else None
    )
    if not isinstance(image_bytes, bytes) or not image_bytes:
        details: dict[str, object] = {"reason": "empty_bytes"}
        if transport_kind is not None:
            details["transport_kind"] = transport_kind
        raise InvalidRequestError(error_message, details=details)
    if _is_raw_media_type(metadata.media_type):
        return _decode_raw_image_bytes_to_matrix(
            cv2_module=cv2_module,
            np_module=np_module,
            image_bytes=image_bytes,
            metadata=metadata,
            imdecode_flags=imdecode_flags,
            copy_raw=copy_raw,
        )

    image_buffer = np_module.frombuffer(image_bytes, dtype=np_module.uint8)
    image_matrix = cv2_module.imdecode(
        image_buffer,
        cv2_module.IMREAD_COLOR if imdecode_flags is None else imdecode_flags,
    )
    if image_matrix is None:
        details = {
            "media_type": metadata.media_type,
            "byte_length": len(image_bytes),
        }
        if transport_kind is not None:
            details["transport_kind"] = transport_kind
        raise InvalidRequestError(error_message, details=details)
    return image_matrix


def prepare_matrix_for_raw_bgr24(
    *,
    cv2_module: Any,
    np_module: Any,
    image_matrix: Any,
    copy_matrix: bool = False,
) -> Any:
    """把任意 OpenCV 常见图片矩阵规整为 HWC uint8 BGR24。"""

    if image_matrix is None or not hasattr(image_matrix, "shape"):
        raise InvalidRequestError("图片矩阵不能为空")
    matrix = image_matrix
    if len(matrix.shape) == 2:
        matrix = cv2_module.cvtColor(matrix, cv2_module.COLOR_GRAY2BGR)
    elif len(matrix.shape) == 3 and int(matrix.shape[2]) == 1:
        matrix = cv2_module.cvtColor(matrix, cv2_module.COLOR_GRAY2BGR)
    elif len(matrix.shape) != 3 or int(matrix.shape[2]) != 3:
        raise InvalidRequestError(
            "raw BGR24 输出要求图片矩阵为 HWC 三通道或灰度图",
            details={"shape": [int(item) for item in getattr(matrix, "shape", ())]},
        )
    if getattr(matrix, "dtype", None) != np_module.uint8:
        matrix = matrix.astype(np_module.uint8)
    if copy_matrix:
        return np_module.ascontiguousarray(matrix, dtype=np_module.uint8).copy()
    return np_module.ascontiguousarray(matrix, dtype=np_module.uint8)


def encode_matrix_to_image_bytes(
    *,
    cv2_module: Any,
    image_matrix: Any,
    extension: str = ".png",
    error_message: str = "图片矩阵无法编码",
) -> bytes:
    """把 OpenCV matrix 编码为 PNG/JPEG/BMP bytes。"""

    normalized_extension = extension.strip().lower() if isinstance(extension, str) and extension.strip() else ".png"
    encode_params: list[int] = []
    if normalized_extension in {".jpg", ".jpeg"}:
        encode_params = [int(cv2_module.IMWRITE_JPEG_QUALITY), 82]
    elif normalized_extension == ".png":
        encode_params = [int(cv2_module.IMWRITE_PNG_COMPRESSION), 1]
    success, encoded_image = cv2_module.imencode(normalized_extension, image_matrix, encode_params)
    if success is not True:
        raise ServiceConfigurationError(error_message)
    return encoded_image.tobytes()


def build_raw_bgr24_payload_fields(*, width: int, height: int) -> dict[str, object]:
    """构造 raw BGR24 image-ref payload 的公共字段。"""

    normalized_width = int(width)
    normalized_height = int(height)
    if normalized_width <= 0 or normalized_height <= 0:
        raise InvalidRequestError(
            "raw BGR24 payload 要求 width/height 为正整数",
            details={"width": width, "height": height},
        )
    return {
        "media_type": IMAGE_MEDIA_TYPE_RAW,
        "width": normalized_width,
        "height": normalized_height,
        "shape": [normalized_height, normalized_width, 3],
        "dtype": IMAGE_DTYPE_UINT8,
        "layout": IMAGE_LAYOUT_HWC,
        "pixel_format": IMAGE_PIXEL_FORMAT_BGR24,
    }


def is_raw_bgr24_payload(payload: object) -> bool:
    """判断 image-ref payload 是否声明为 raw BGR24。"""

    metadata = normalize_image_payload_metadata(payload)
    return (
        _is_raw_media_type(metadata.media_type)
        and metadata.dtype == IMAGE_DTYPE_UINT8
        and metadata.layout == IMAGE_LAYOUT_HWC
        and metadata.pixel_format == IMAGE_PIXEL_FORMAT_BGR24
    )


def _decode_raw_image_bytes_to_matrix(
    *,
    cv2_module: Any,
    np_module: Any,
    image_bytes: bytes,
    metadata: ImagePayloadMetadata,
    imdecode_flags: int | None,
    copy_raw: bool,
) -> Any:
    """把 raw image bytes 解释为 OpenCV matrix。"""

    shape = metadata.shape
    if not shape:
        raise InvalidRequestError("raw 图片缺少 shape")
    normalized_dtype = metadata.dtype
    normalized_layout = metadata.layout
    normalized_pixel_format = metadata.pixel_format
    if normalized_dtype != IMAGE_DTYPE_UINT8:
        raise InvalidRequestError("raw 图片当前仅支持 dtype=uint8", details={"dtype": metadata.dtype})
    if normalized_layout != IMAGE_LAYOUT_HWC:
        raise InvalidRequestError("raw 图片当前仅支持 layout=HWC", details={"layout": metadata.layout})

    if normalized_pixel_format == IMAGE_PIXEL_FORMAT_BGR24:
        validate_raw_bgr24_bytes(
            image_bytes=image_bytes,
            shape=shape,
            dtype=metadata.dtype,
            layout=metadata.layout,
            pixel_format=metadata.pixel_format,
        )
        matrix = np_module.frombuffer(image_bytes, dtype=np_module.uint8).reshape(shape)
    elif normalized_pixel_format == IMAGE_PIXEL_FORMAT_RGB24:
        _validate_raw_3_channel_bytes(image_bytes=image_bytes, shape=shape, pixel_format=normalized_pixel_format)
        rgb_matrix = np_module.frombuffer(image_bytes, dtype=np_module.uint8).reshape(shape)
        matrix = cv2_module.cvtColor(rgb_matrix, cv2_module.COLOR_RGB2BGR)
    elif normalized_pixel_format == IMAGE_PIXEL_FORMAT_GRAY8:
        matrix = _decode_gray8_bytes(np_module=np_module, image_bytes=image_bytes, shape=shape)
    else:
        raise InvalidRequestError(
            "raw 图片 pixel_format 当前仅支持 bgr24/rgb24/gray8",
            details={"pixel_format": metadata.pixel_format},
        )

    if copy_raw and hasattr(matrix, "copy"):
        matrix = matrix.copy()
    return _apply_raw_decode_flags(
        cv2_module=cv2_module,
        matrix=matrix,
        imdecode_flags=imdecode_flags,
    )


def _apply_raw_decode_flags(*, cv2_module: Any, matrix: Any, imdecode_flags: int | None) -> Any:
    """按 OpenCV imdecode flags 调整 raw matrix 输出形态。"""

    if imdecode_flags is None:
        return matrix
    if imdecode_flags == getattr(cv2_module, "IMREAD_GRAYSCALE", 0):
        if len(matrix.shape) == 2:
            return matrix
        return cv2_module.cvtColor(matrix, cv2_module.COLOR_BGR2GRAY)
    if imdecode_flags == getattr(cv2_module, "IMREAD_COLOR", 1):
        if len(matrix.shape) == 2:
            return cv2_module.cvtColor(matrix, cv2_module.COLOR_GRAY2BGR)
        return matrix
    return matrix


def _decode_gray8_bytes(*, np_module: Any, image_bytes: bytes, shape: tuple[int, ...]) -> Any:
    """把 gray8 raw bytes 解释为灰度矩阵。"""

    if len(shape) == 2:
        height, width = int(shape[0]), int(shape[1])
    elif len(shape) == 3 and int(shape[2]) == 1:
        height, width = int(shape[0]), int(shape[1])
    else:
        raise InvalidRequestError("raw gray8 图片要求 shape=[height,width] 或 [height,width,1]")
    expected_size = height * width
    if len(image_bytes) != expected_size:
        raise InvalidRequestError(
            "raw gray8 图片 bytes 长度与 shape 不一致",
            details={"expected_size": expected_size, "actual_size": len(image_bytes)},
        )
    return np_module.frombuffer(image_bytes, dtype=np_module.uint8).reshape((height, width))


def _validate_raw_3_channel_bytes(
    *,
    image_bytes: bytes,
    shape: tuple[int, ...],
    pixel_format: str,
) -> None:
    """校验三通道 raw image bytes 长度。"""

    if len(shape) != 3 or int(shape[2]) != 3:
        raise InvalidRequestError(
            "raw 三通道图片要求 shape=[height,width,3]",
            details={"shape": list(shape), "pixel_format": pixel_format},
        )
    expected_size = int(shape[0]) * int(shape[1]) * int(shape[2])
    if len(image_bytes) != expected_size:
        raise InvalidRequestError(
            "raw 三通道图片 bytes 长度与 shape 不一致",
            details={"expected_size": expected_size, "actual_size": len(image_bytes)},
        )


def _normalize_shape(value: object) -> tuple[int, ...]:
    """规范化 shape 字段。"""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise InvalidRequestError("image payload shape 必须是数组")
    normalized_shape: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise InvalidRequestError("image payload shape 只能包含正整数")
        if item <= 0:
            raise InvalidRequestError("image payload shape 只能包含正整数")
        normalized_shape.append(int(item))
    return tuple(normalized_shape)


def _normalize_layout(value: object) -> str | None:
    """规范化 raw layout。"""

    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        return None
    return normalized_value.upper()


def _normalize_pixel_format(value: object) -> str | None:
    """规范化 pixel_format。"""

    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        return None
    collapsed = normalized_value.replace("-", "").replace("_", "").lower()
    if collapsed in {"bgr", "bgr24"}:
        return IMAGE_PIXEL_FORMAT_BGR24
    if collapsed in {"rgb", "rgb24"}:
        return IMAGE_PIXEL_FORMAT_RGB24
    if collapsed in {"gray", "grey", "gray8", "grey8", "mono", "mono8"}:
        return IMAGE_PIXEL_FORMAT_GRAY8
    return collapsed


def _is_raw_media_type(media_type: str) -> bool:
    """判断 media_type 是否为 raw 图片。"""

    return media_type.strip().lower() in {IMAGE_MEDIA_TYPE_RAW, "application/octet-stream+image-raw"}


def _normalize_optional_dimension(value: object) -> int | None:
    """规范化可选图片尺寸。"""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        normalized_value = int(value)
        return normalized_value if normalized_value > 0 and normalized_value == value else None
    return None


def _normalize_optional_text(value: object) -> str | None:
    """规范化可选字符串。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None
