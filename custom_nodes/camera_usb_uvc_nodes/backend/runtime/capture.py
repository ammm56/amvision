"""USB / UVC 相机 OpenCV capture 操作。"""

from __future__ import annotations

from typing import Any
import math

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.validators import normalize_optional_text


def require_opencv_imports() -> tuple[Any, Any]:
    """加载 OpenCV 与 NumPy 依赖。"""

    try:
        import cv2
        import numpy as np
    except ImportError as error:  # pragma: no cover - 仅在运行环境缺依赖时触发
        raise ServiceConfigurationError("当前运行环境缺少 opencv-python 或 numpy 依赖") from error
    return cv2, np


def create_video_capture(*, source: int | str, api_preference: int) -> object:
    """创建一个 OpenCV VideoCapture 实例。"""

    cv2_module, _ = require_opencv_imports()
    return cv2_module.VideoCapture(source, api_preference)


def open_video_capture_or_raise(
    *,
    source: int | str,
    api_preference: int,
    backend_preference: str,
    node_id: str,
) -> object:
    """创建并打开一个相机句柄；失败时返回明确错误。"""

    video_capture = create_video_capture(source=source, api_preference=api_preference)
    if video_capture is None:
        raise InvalidRequestError(
            "当前节点无法创建相机采集句柄",
            details={"node_id": node_id, "backend_preference": backend_preference},
        )
    try:
        is_opened = bool(video_capture.isOpened())
    except Exception as error:  # pragma: no cover - 第三方运行时异常防御
        safe_release_capture(video_capture)
        raise ServiceConfigurationError(
            "当前节点无法判断相机句柄是否已打开",
            details={"node_id": node_id, "backend_preference": backend_preference},
        ) from error
    if not is_opened:
        safe_release_capture(video_capture)
        raise InvalidRequestError(
            "当前节点无法打开指定 USB / UVC 相机",
            details={
                "node_id": node_id,
                "backend_preference": backend_preference,
                "source": source,
            },
        )
    return video_capture


def configure_video_capture(
    video_capture: object,
    *,
    width: int | None,
    height: int | None,
    fps: float | None,
    cv2_module: Any,
) -> None:
    """按需给 VideoCapture 设置宽高和帧率。"""

    if width is not None:
        safe_capture_set(video_capture, property_id=int(cv2_module.CAP_PROP_FRAME_WIDTH), value=float(width))
    if height is not None:
        safe_capture_set(video_capture, property_id=int(cv2_module.CAP_PROP_FRAME_HEIGHT), value=float(height))
    if fps is not None:
        safe_capture_set(video_capture, property_id=int(cv2_module.CAP_PROP_FPS), value=float(fps))


def read_last_frame(
    video_capture: object,
    *,
    warmup_frame_count: int,
    retry_read_count: int,
    node_id: str,
    source_details: dict[str, object],
) -> tuple[Any, int]:
    """从 VideoCapture 中读取最后一帧成功结果。"""

    total_attempts = max(1, int(warmup_frame_count) + int(retry_read_count))
    last_frame = None
    successful_reads = 0
    for _ in range(total_attempts):
        success, frame = video_capture.read()
        if success is True and frame is not None:
            last_frame = frame
            successful_reads += 1
    if last_frame is None:
        raise InvalidRequestError(
            "当前节点无法从 USB / UVC 相机读取图像帧",
            details={"node_id": node_id, **source_details},
        )
    return last_frame, successful_reads


def get_frame_dimensions(frame: object) -> tuple[int, int, int]:
    """从图像帧中提取宽、高和通道数。"""

    if not hasattr(frame, "shape"):
        raise InvalidRequestError("当前节点读取到的图像帧缺少 shape 信息")
    shape = getattr(frame, "shape")
    if not isinstance(shape, tuple) or len(shape) < 2:
        raise InvalidRequestError("当前节点读取到的图像帧 shape 非法")
    height = int(shape[0])
    width = int(shape[1])
    channels = int(shape[2]) if len(shape) >= 3 else 1
    return width, height, channels


def encode_frame_bytes(
    *,
    frame: object,
    output_format: str,
    jpeg_quality: int,
    cv2_module: Any,
) -> tuple[bytes, str]:
    """把相机图像帧编码为 PNG 或 JPEG 字节。"""

    if output_format == "jpeg":
        success, encoded = cv2_module.imencode(
            ".jpg",
            frame,
            [int(cv2_module.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
        )
        media_type = "image/jpeg"
    else:
        success, encoded = cv2_module.imencode(".png", frame)
        media_type = "image/png"
    if success is not True:
        raise ServiceConfigurationError("当前节点无法编码相机图像帧")
    return bytes(encoded.tobytes()), media_type


def get_capture_backend_name(video_capture: object) -> str | None:
    """读取当前 OpenCV capture 实际 backend 名称。"""

    backend_name_getter = getattr(video_capture, "getBackendName", None)
    if not callable(backend_name_getter):
        return None
    try:
        backend_name = backend_name_getter()
    except Exception:  # pragma: no cover - 第三方运行时异常防御
        return None
    return normalize_optional_text(backend_name)


def read_capture_property(video_capture: object, *, property_id: int) -> float | None:
    """安全读取 capture 数值属性。"""

    getter = getattr(video_capture, "get", None)
    if not callable(getter):
        return None
    try:
        value = getter(property_id)
    except Exception:  # pragma: no cover - 第三方运行时异常防御
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return round(float(value), 4)


def safe_release_capture(video_capture: object | None) -> None:
    """安全释放 VideoCapture 句柄。"""

    if video_capture is None:
        return
    releaser = getattr(video_capture, "release", None)
    if callable(releaser):
        try:
            releaser()
        except Exception:  # pragma: no cover - 第三方运行时异常防御
            return


def safe_capture_set(video_capture: object, *, property_id: int, value: float) -> None:
    """尝试给 capture 设置属性；失败时静默跳过。"""

    setter = getattr(video_capture, "set", None)
    if not callable(setter):
        return
    try:
        setter(property_id, value)
    except Exception:  # pragma: no cover - 第三方运行时异常防御
        return
