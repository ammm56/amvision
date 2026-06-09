"""USB / UVC 相机节点包 backend 共享 helper。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.nodes.runtime_support import copy_image_payload, register_image_bytes
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


BACKEND_PREFERENCE_VALUES: tuple[str, ...] = (
    "any",
    "dshow",
    "msmf",
    "v4l2",
    "gstreamer",
)

OUTPUT_FORMAT_VALUES: tuple[str, ...] = ("png", "jpeg")


@dataclass(frozen=True)
class UsbCameraEnumerateConfig:
    """描述 enumerate-devices 节点的最终运行配置。"""

    start_index: int
    device_count: int
    backend_preference: str
    api_preference: int
    probe_frame: bool
    warmup_frame_count: int


@dataclass(frozen=True)
class UsbCameraCaptureConfig:
    """描述 capture-frame 节点的最终运行配置。"""

    source_kind: str
    device_index: int | None
    device_path: str | None
    backend_preference: str
    api_preference: int
    width: int | None
    height: int | None
    fps: float | None
    warmup_frame_count: int
    retry_read_count: int
    output_format: str
    jpeg_quality: int
    output_object_key: str | None
    overwrite: bool

    @property
    def source_value(self) -> int | str:
        """返回可直接传入 OpenCV VideoCapture 的 source。"""

        if self.source_kind == "device-path":
            assert self.device_path is not None
            return self.device_path
        assert self.device_index is not None
        return self.device_index


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


def resolve_enumerate_config(request: WorkflowNodeExecutionRequest, *, cv2_module: Any) -> UsbCameraEnumerateConfig:
    """从节点参数与可选 request 输入解析 enumerate-devices 配置。"""

    request_override = require_optional_request_object(request.input_values.get("request"))
    backend_preference, api_preference = resolve_backend_preference(
        request_override.get("backend_preference", request.parameters.get("backend_preference")),
        cv2_module=cv2_module,
    )
    return UsbCameraEnumerateConfig(
        start_index=require_non_negative_int(
            request_override.get("start_index", request.parameters.get("start_index", 0)),
            field_name="start_index",
        ),
        device_count=require_positive_int(
            request_override.get("device_count", request.parameters.get("device_count", 8)),
            field_name="device_count",
        ),
        backend_preference=backend_preference,
        api_preference=api_preference,
        probe_frame=require_bool(
            request_override.get("probe_frame", request.parameters.get("probe_frame", True)),
            field_name="probe_frame",
        ),
        warmup_frame_count=require_non_negative_int(
            request_override.get("warmup_frame_count", request.parameters.get("warmup_frame_count", 1)),
            field_name="warmup_frame_count",
        ),
    )


def resolve_capture_config(request: WorkflowNodeExecutionRequest, *, cv2_module: Any) -> UsbCameraCaptureConfig:
    """从节点参数与可选 request 输入解析 capture-frame 配置。"""

    request_override = require_optional_request_object(request.input_values.get("request"))
    backend_preference, api_preference = resolve_backend_preference(
        request_override.get("backend_preference", request.parameters.get("backend_preference")),
        cv2_module=cv2_module,
    )
    device_path = normalize_optional_text(
        request_override.get("device_path", request.parameters.get("device_path"))
    )
    device_index_raw = request_override.get("device_index", request.parameters.get("device_index", 0))
    device_index = None if device_path is not None else require_non_negative_int(device_index_raw, field_name="device_index")
    output_format = resolve_output_format(
        request_override.get("output_format", request.parameters.get("output_format", "png"))
    )
    return UsbCameraCaptureConfig(
        source_kind="device-path" if device_path is not None else "device-index",
        device_index=device_index,
        device_path=device_path,
        backend_preference=backend_preference,
        api_preference=api_preference,
        width=require_optional_positive_int(
            request_override.get("width", request.parameters.get("width")),
            field_name="width",
        ),
        height=require_optional_positive_int(
            request_override.get("height", request.parameters.get("height")),
            field_name="height",
        ),
        fps=require_optional_positive_float(
            request_override.get("fps", request.parameters.get("fps")),
            field_name="fps",
        ),
        warmup_frame_count=require_non_negative_int(
            request_override.get("warmup_frame_count", request.parameters.get("warmup_frame_count", 2)),
            field_name="warmup_frame_count",
        ),
        retry_read_count=require_positive_int(
            request_override.get("retry_read_count", request.parameters.get("retry_read_count", 3)),
            field_name="retry_read_count",
        ),
        output_format=output_format,
        jpeg_quality=require_uint8_range(
            request_override.get("jpeg_quality", request.parameters.get("jpeg_quality", 95)),
            field_name="jpeg_quality",
            minimum=1,
            maximum=100,
        ),
        output_object_key=normalize_optional_text(
            request_override.get("output_object_key", request.parameters.get("output_object_key"))
        ),
        overwrite=require_bool(
            request_override.get("overwrite", request.parameters.get("overwrite", True)),
            field_name="overwrite",
        ),
    )


def resolve_backend_preference(raw_value: object, *, cv2_module: Any) -> tuple[str, int]:
    """把 backend_preference 解析为 OpenCV backend 常量。"""

    normalized_value = "any" if raw_value is None else require_string(raw_value, field_name="backend_preference").lower()
    if normalized_value not in BACKEND_PREFERENCE_VALUES:
        raise InvalidRequestError(
            "backend_preference 不在支持列表中",
            details={"allowed_values": list(BACKEND_PREFERENCE_VALUES)},
        )
    constant_name_by_preference = {
        "any": "CAP_ANY",
        "dshow": "CAP_DSHOW",
        "msmf": "CAP_MSMF",
        "v4l2": "CAP_V4L2",
        "gstreamer": "CAP_GSTREAMER",
    }
    constant_name = constant_name_by_preference[normalized_value]
    if not hasattr(cv2_module, constant_name):
        raise InvalidRequestError(
            "当前运行环境不支持指定 backend_preference",
            details={"backend_preference": normalized_value},
        )
    return normalized_value, int(getattr(cv2_module, constant_name))


def resolve_output_format(raw_value: object) -> str:
    """规范化输出图片格式。"""

    normalized_value = require_string(raw_value, field_name="output_format").lower()
    if normalized_value not in OUTPUT_FORMAT_VALUES:
        raise InvalidRequestError(
            "output_format 仅支持 png 或 jpeg",
            details={"allowed_values": list(OUTPUT_FORMAT_VALUES)},
        )
    return normalized_value


def open_video_capture_or_raise(
    *,
    source: int | str,
    api_preference: int,
    backend_preference: str,
    node_id: str,
) -> object:
    """创建并打开一个相机句柄；失败时返回明确错误。"""

    capture = create_video_capture(source=source, api_preference=api_preference)
    if capture is None:
        raise InvalidRequestError(
            "当前节点无法创建相机采集句柄",
            details={"node_id": node_id, "backend_preference": backend_preference},
        )
    try:
        is_opened = bool(capture.isOpened())
    except Exception as error:  # pragma: no cover - 第三方运行时异常防御
        safe_release_capture(capture)
        raise ServiceConfigurationError(
            "当前节点无法判断相机句柄是否已打开",
            details={"node_id": node_id, "backend_preference": backend_preference},
        ) from error
    if not is_opened:
        safe_release_capture(capture)
        raise InvalidRequestError(
            "当前节点无法打开指定 USB / UVC 相机",
            details={
                "node_id": node_id,
                "backend_preference": backend_preference,
                "source": source,
            },
        )
    return capture


def configure_video_capture(
    capture: object,
    *,
    width: int | None,
    height: int | None,
    fps: float | None,
    cv2_module: Any,
) -> None:
    """按需给 VideoCapture 设置宽高和帧率。"""

    if width is not None:
        _safe_capture_set(capture, property_id=int(cv2_module.CAP_PROP_FRAME_WIDTH), value=float(width))
    if height is not None:
        _safe_capture_set(capture, property_id=int(cv2_module.CAP_PROP_FRAME_HEIGHT), value=float(height))
    if fps is not None:
        _safe_capture_set(capture, property_id=int(cv2_module.CAP_PROP_FPS), value=float(fps))


def read_last_frame(
    capture: object,
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
        success, frame = capture.read()
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


def build_captured_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    content: bytes,
    media_type: str,
    width: int,
    height: int,
    output_object_key: str | None,
    overwrite: bool,
) -> dict[str, object]:
    """把相机帧注册为 image-ref；需要时再复制到目标 object key。"""

    memory_payload = register_image_bytes(
        request,
        content=content,
        media_type=media_type,
        width=width,
        height=height,
    )
    if output_object_key is None:
        return memory_payload
    return copy_image_payload(
        request,
        source_payload=memory_payload,
        object_key=output_object_key,
        overwrite=overwrite,
        variant_name="usb-capture-frame",
    )


def get_capture_backend_name(capture: object) -> str | None:
    """读取当前 OpenCV capture 实际 backend 名称。"""

    backend_name_getter = getattr(capture, "getBackendName", None)
    if not callable(backend_name_getter):
        return None
    try:
        backend_name = backend_name_getter()
    except Exception:  # pragma: no cover - 第三方运行时异常防御
        return None
    return normalize_optional_text(backend_name)


def read_capture_property(capture: object, *, property_id: int) -> float | None:
    """安全读取 capture 数值属性。"""

    getter = getattr(capture, "get", None)
    if not callable(getter):
        return None
    try:
        value = getter(property_id)
    except Exception:  # pragma: no cover - 第三方运行时异常防御
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or float(value) <= 0:
        return None
    return round(float(value), 4)


def safe_release_capture(capture: object | None) -> None:
    """安全释放 VideoCapture 句柄。"""

    if capture is None:
        return
    releaser = getattr(capture, "release", None)
    if callable(releaser):
        try:
            releaser()
        except Exception:  # pragma: no cover - 第三方运行时异常防御
            return


def build_value_payload(value: object) -> dict[str, object]:
    """把 JSON 安全值包装成 value.v1。"""

    return {"value": normalize_json_safe_value(value)}


def require_optional_request_object(payload: object) -> dict[str, object]:
    """读取可选 request(value.v1) 输入，并要求 value 必须是对象。"""

    if payload is None:
        return {}
    if not isinstance(payload, dict) or "value" not in payload:
        raise InvalidRequestError("request payload 必须是包含 value 的对象")
    raw_value = payload.get("value")
    if not isinstance(raw_value, dict):
        raise InvalidRequestError("request.value 必须是对象")
    return {str(key): raw_value[key] for key in raw_value}


def normalize_json_safe_value(value: object) -> object:
    """递归把值规范化为 JSON 安全结构。"""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return [normalize_json_safe_value(item) for item in value]
    if isinstance(value, list):
        return [normalize_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_json_safe_value(item) for key, item in value.items()}
    raise InvalidRequestError(
        "当前节点只支持 JSON 安全值",
        details={"value_type": value.__class__.__name__},
    )


def require_positive_int(raw_value: object, *, field_name: str) -> int:
    """把输入解析为正整数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return int(raw_value)


def require_non_negative_int(raw_value: object, *, field_name: str) -> int:
    """把输入解析为非负整数。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return int(raw_value)


def require_optional_positive_int(raw_value: object, *, field_name: str) -> int | None:
    """把输入解析为可选正整数。"""

    if raw_value is None:
        return None
    return require_positive_int(raw_value, field_name=field_name)


def require_optional_positive_float(raw_value: object, *, field_name: str) -> float | None:
    """把输入解析为可选正浮点数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    if float(raw_value) <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return float(raw_value)


def require_uint8_range(
    raw_value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """把输入解析为指定闭区间内的整数。"""

    normalized_value = require_positive_int(raw_value, field_name=field_name)
    if normalized_value < minimum or normalized_value > maximum:
        raise InvalidRequestError(f"{field_name} 必须在 {minimum} 到 {maximum} 之间")
    return normalized_value


def require_bool(raw_value: object, *, field_name: str) -> bool:
    """把输入解析为布尔值。"""

    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return bool(raw_value)


def require_string(raw_value: object, *, field_name: str) -> str:
    """把输入解析为非空字符串。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_value.strip()


def normalize_optional_text(raw_value: object) -> str | None:
    """规范化可选字符串；空值返回 None。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    return raw_value.strip()


def _safe_capture_set(capture: object, *, property_id: int, value: float) -> None:
    """尝试给 capture 设置属性；失败时静默跳过。"""

    setter = getattr(capture, "set", None)
    if not callable(setter):
        return
    try:
        setter(property_id, value)
    except Exception:  # pragma: no cover - 第三方运行时异常防御
        return

