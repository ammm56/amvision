"""USB / UVC 相机节点包 backend 共享 helper。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

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
CAMERA_SESSION_REGISTRY_METADATA_KEY = "usb_camera_session_registry"


@dataclass(frozen=True)
class UsbCameraParameterSpec:
    """描述单个可读写相机参数的映射关系。"""

    constant_name: str
    value_kind: str = "float"
    writable: bool = True


CAMERA_PARAMETER_SPECS: dict[str, UsbCameraParameterSpec] = {
    "width": UsbCameraParameterSpec("CAP_PROP_FRAME_WIDTH", value_kind="int"),
    "height": UsbCameraParameterSpec("CAP_PROP_FRAME_HEIGHT", value_kind="int"),
    "fps": UsbCameraParameterSpec("CAP_PROP_FPS", value_kind="float"),
    "brightness": UsbCameraParameterSpec("CAP_PROP_BRIGHTNESS"),
    "contrast": UsbCameraParameterSpec("CAP_PROP_CONTRAST"),
    "saturation": UsbCameraParameterSpec("CAP_PROP_SATURATION"),
    "hue": UsbCameraParameterSpec("CAP_PROP_HUE"),
    "gain": UsbCameraParameterSpec("CAP_PROP_GAIN"),
    "exposure": UsbCameraParameterSpec("CAP_PROP_EXPOSURE"),
    "sharpness": UsbCameraParameterSpec("CAP_PROP_SHARPNESS"),
    "focus": UsbCameraParameterSpec("CAP_PROP_FOCUS"),
    "zoom": UsbCameraParameterSpec("CAP_PROP_ZOOM"),
    "gamma": UsbCameraParameterSpec("CAP_PROP_GAMMA"),
    "temperature": UsbCameraParameterSpec("CAP_PROP_TEMPERATURE"),
    "buffer_size": UsbCameraParameterSpec("CAP_PROP_BUFFERSIZE", value_kind="int"),
    "auto_focus": UsbCameraParameterSpec("CAP_PROP_AUTOFOCUS", value_kind="bool"),
}
CAMERA_PARAMETER_NAME_VALUES: tuple[str, ...] = tuple(
    sorted(
        (
            *CAMERA_PARAMETER_SPECS.keys(),
            "backend_name",
            "session_handle",
            "source_kind",
            "device_index",
            "device_path",
            "backend_preference",
            "requested_width",
            "requested_height",
            "requested_fps",
            "opened_at",
            "last_read_at",
            "successful_reads_total",
            "last_frame_width",
            "last_frame_height",
            "last_frame_channels",
        )
    )
)
DEFAULT_CAMERA_PARAMETER_NAMES: tuple[str, ...] = (
    "width",
    "height",
    "fps",
    "backend_name",
)

_RUNTIME_CAMERA_SESSION_REGISTRIES: WeakKeyDictionary[object, UsbCameraSessionRegistry] = WeakKeyDictionary()
_RUNTIME_CAMERA_SESSION_REGISTRIES_LOCK = Lock()


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


@dataclass(frozen=True)
class UsbCameraOpenConfig:
    """描述 open-device 节点的最终运行配置。"""

    source_kind: str
    device_index: int | None
    device_path: str | None
    backend_preference: str
    api_preference: int
    width: int | None
    height: int | None
    fps: float | None
    probe_frame: bool
    warmup_frame_count: int
    retry_read_count: int

    @property
    def source_value(self) -> int | str:
        """返回可直接传入 OpenCV VideoCapture 的 source。"""

        if self.source_kind == "device-path":
            assert self.device_path is not None
            return self.device_path
        assert self.device_index is not None
        return self.device_index


@dataclass(frozen=True)
class UsbCameraSessionReadConfig:
    """描述 read-latest-frame 节点的最终运行配置。"""

    warmup_frame_count: int
    retry_read_count: int
    output_format: str
    jpeg_quality: int
    output_object_key: str | None
    overwrite: bool


@dataclass(frozen=True)
class UsbCameraGetParametersConfig:
    """描述 get-parameter 节点的最终运行配置。"""

    parameter_names: tuple[str, ...]


@dataclass(frozen=True)
class UsbCameraSetParametersConfig:
    """描述 set-parameter 节点的最终运行配置。"""

    parameter_values: dict[str, object]
    verify_after_set: bool


@dataclass
class UsbCameraSessionEntry:
    """描述一个已打开的 USB / UVC 相机会话。"""

    session_handle: str
    capture: object
    source_kind: str
    device_index: int | None
    device_path: str | None
    backend_preference: str
    api_preference: int
    opened_at: str
    requested_width: int | None = None
    requested_height: int | None = None
    requested_fps: float | None = None
    backend_name: str | None = None
    successful_reads_total: int = 0
    last_read_at: str | None = None
    last_frame_width: int | None = None
    last_frame_height: int | None = None
    last_frame_channels: int | None = None


@dataclass
class UsbCameraSessionRegistry:
    """管理一组打开中的 USB / UVC 相机会话。"""

    _entries: dict[str, UsbCameraSessionEntry] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def register_entry(self, entry: UsbCameraSessionEntry) -> UsbCameraSessionEntry:
        """登记一条已打开会话。"""

        with self._lock:
            self._entries[entry.session_handle] = entry
        return entry

    def get_entry(self, session_handle: str) -> UsbCameraSessionEntry | None:
        """按句柄读取已打开会话。"""

        normalized_session_handle = require_string(session_handle, field_name="session_handle")
        with self._lock:
            return self._entries.get(normalized_session_handle)

    def pop_entry(self, session_handle: str) -> UsbCameraSessionEntry | None:
        """按句柄移除并返回一条会话。"""

        normalized_session_handle = require_string(session_handle, field_name="session_handle")
        with self._lock:
            return self._entries.pop(normalized_session_handle, None)

    def close_all(self) -> None:
        """释放当前 registry 内的全部相机会话。"""

        with self._lock:
            entries = tuple(self._entries.values())
            self._entries.clear()
        for entry in entries:
            safe_release_capture(entry.capture)


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


def resolve_open_config(request: WorkflowNodeExecutionRequest, *, cv2_module: Any) -> UsbCameraOpenConfig:
    """从节点参数与可选 request 输入解析 open-device 配置。"""

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
    return UsbCameraOpenConfig(
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
        probe_frame=require_bool(
            request_override.get("probe_frame", request.parameters.get("probe_frame", True)),
            field_name="probe_frame",
        ),
        warmup_frame_count=require_non_negative_int(
            request_override.get("warmup_frame_count", request.parameters.get("warmup_frame_count", 1)),
            field_name="warmup_frame_count",
        ),
        retry_read_count=require_positive_int(
            request_override.get("retry_read_count", request.parameters.get("retry_read_count", 1)),
            field_name="retry_read_count",
        ),
    )


def resolve_session_read_config(request: WorkflowNodeExecutionRequest) -> UsbCameraSessionReadConfig:
    """从节点参数与可选 request 输入解析 read-latest-frame 配置。"""

    request_override = require_optional_request_object(request.input_values.get("request"))
    return UsbCameraSessionReadConfig(
        warmup_frame_count=require_non_negative_int(
            request_override.get("warmup_frame_count", request.parameters.get("warmup_frame_count", 0)),
            field_name="warmup_frame_count",
        ),
        retry_read_count=require_positive_int(
            request_override.get("retry_read_count", request.parameters.get("retry_read_count", 3)),
            field_name="retry_read_count",
        ),
        output_format=resolve_output_format(
            request_override.get("output_format", request.parameters.get("output_format", "png"))
        ),
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


def resolve_get_parameters_config(request: WorkflowNodeExecutionRequest) -> UsbCameraGetParametersConfig:
    """从节点参数与可选 request 输入解析 get-parameter 配置。"""

    request_override = require_optional_request_object(request.input_values.get("request"))
    raw_parameter_names = request_override.get(
        "parameter_names",
        request.parameters.get("parameter_names", list(DEFAULT_CAMERA_PARAMETER_NAMES)),
    )
    return UsbCameraGetParametersConfig(
        parameter_names=tuple(require_parameter_name_list(raw_parameter_names))
    )


def resolve_set_parameters_config(request: WorkflowNodeExecutionRequest) -> UsbCameraSetParametersConfig:
    """从节点参数与可选 request 输入解析 set-parameter 配置。"""

    request_override = require_optional_request_object(request.input_values.get("request"))
    raw_parameter_values = request_override.get(
        "parameter_values",
        request.parameters.get("parameter_values", {}),
    )
    return UsbCameraSetParametersConfig(
        parameter_values=require_parameter_value_mapping(raw_parameter_values),
        verify_after_set=require_bool(
            request_override.get("verify_after_set", request.parameters.get("verify_after_set", True)),
            field_name="verify_after_set",
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


def resolve_camera_session_registry(request: WorkflowNodeExecutionRequest) -> UsbCameraSessionRegistry:
    """按运行时范围返回当前 USB / UVC 相机会话 registry。"""

    runtime_context = request.runtime_context
    if runtime_context is not None:
        try:
            with _RUNTIME_CAMERA_SESSION_REGISTRIES_LOCK:
                registry = _RUNTIME_CAMERA_SESSION_REGISTRIES.get(runtime_context)
                if registry is None:
                    registry = UsbCameraSessionRegistry()
                    _RUNTIME_CAMERA_SESSION_REGISTRIES[runtime_context] = registry
                return registry
        except TypeError:
            pass

    execution_metadata = request.execution_metadata
    registry = execution_metadata.get(CAMERA_SESSION_REGISTRY_METADATA_KEY)
    if registry is None:
        registry = UsbCameraSessionRegistry()
        execution_metadata[CAMERA_SESSION_REGISTRY_METADATA_KEY] = registry
    if not isinstance(registry, UsbCameraSessionRegistry):
        raise ServiceConfigurationError(
            "当前执行上下文中的 USB 相机会话 registry 非法",
            details={"node_id": request.node_id},
        )
    return registry


def open_camera_session(
    request: WorkflowNodeExecutionRequest,
    *,
    config: UsbCameraOpenConfig,
    cv2_module: Any,
) -> tuple[UsbCameraSessionEntry, dict[str, object]]:
    """打开一个可跨节点复用的 USB / UVC 相机会话。"""

    capture = open_video_capture_or_raise(
        source=config.source_value,
        api_preference=config.api_preference,
        backend_preference=config.backend_preference,
        node_id=request.node_id,
    )
    try:
        configure_video_capture(
            capture,
            width=config.width,
            height=config.height,
            fps=config.fps,
            cv2_module=cv2_module,
        )
        entry = UsbCameraSessionEntry(
            session_handle=f"usb-camera-session-{uuid4().hex}",
            capture=capture,
            source_kind=config.source_kind,
            device_index=config.device_index,
            device_path=config.device_path,
            backend_preference=config.backend_preference,
            api_preference=config.api_preference,
            opened_at=_now_isoformat(),
            requested_width=config.width,
            requested_height=config.height,
            requested_fps=config.fps,
            backend_name=get_capture_backend_name(capture),
        )
        summary = build_camera_session_summary(entry, operation="open_device")
        summary["probe_frame"] = config.probe_frame
        if config.probe_frame:
            frame, successful_reads = read_last_frame(
                capture,
                warmup_frame_count=config.warmup_frame_count,
                retry_read_count=config.retry_read_count,
                node_id=request.node_id,
                source_details={
                    "source_kind": config.source_kind,
                    "device_index": config.device_index,
                    "device_path": config.device_path,
                },
            )
            update_camera_session_read_state(entry, frame=frame, successful_reads=successful_reads)
            summary.update(
                {
                    "successful_reads": successful_reads,
                    "probe_frame_width": entry.last_frame_width,
                    "probe_frame_height": entry.last_frame_height,
                    "probe_frame_channels": entry.last_frame_channels,
                }
            )
        summary.update(read_session_capture_observation(entry, cv2_module=cv2_module))
        resolve_camera_session_registry(request).register_entry(entry)
        return entry, summary
    except Exception:
        safe_release_capture(capture)
        raise


def require_camera_session_payload(payload: object) -> dict[str, object]:
    """校验 camera-session.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("camera-session payload 必须是对象")
    session_handle = payload.get("session_handle")
    normalized_session_handle = require_string(session_handle, field_name="session_handle")
    normalized_payload: dict[str, object] = {
        "transport": "usb-uvc",
        "session_handle": normalized_session_handle,
    }
    for key in (
        "source_kind",
        "device_index",
        "device_path",
        "backend_preference",
        "backend_name",
        "opened_at",
        "requested_width",
        "requested_height",
        "requested_fps",
        "successful_reads_total",
        "last_read_at",
        "last_frame_width",
        "last_frame_height",
        "last_frame_channels",
    ):
        if key in payload:
            normalized_payload[key] = normalize_json_safe_value(payload[key])
    return normalized_payload


def require_camera_session_entry(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "session",
) -> tuple[dict[str, object], UsbCameraSessionEntry]:
    """从输入端口读取 camera-session.v1，并解析到底层会话。"""

    payload = require_camera_session_payload(request.input_values.get(input_name))
    session_handle = str(payload["session_handle"])
    entry = resolve_camera_session_registry(request).get_entry(session_handle)
    if entry is None:
        raise InvalidRequestError(
            "指定 USB / UVC 相机会话不存在或已关闭",
            details={"node_id": request.node_id, "session_handle": session_handle},
        )
    return payload, entry


def close_camera_session(
    request: WorkflowNodeExecutionRequest,
    *,
    input_name: str = "session",
) -> dict[str, object]:
    """关闭一个已打开的 USB / UVC 相机会话，并返回关闭摘要。"""

    payload = require_camera_session_payload(request.input_values.get(input_name))
    session_handle = str(payload["session_handle"])
    entry = resolve_camera_session_registry(request).pop_entry(session_handle)
    if entry is None:
        return build_value_payload(
            {
                "transport": "usb-uvc",
                "operation": "close_device",
                "session_handle": session_handle,
                "closed": False,
                "already_closed": True,
            }
        )

    summary = build_camera_session_summary(entry, operation="close_device")
    summary["closed"] = True
    safe_release_capture(entry.capture)
    return build_value_payload(summary)


def build_camera_session_payload(entry: UsbCameraSessionEntry) -> dict[str, object]:
    """把打开中的会话条目转换成 camera-session.v1 payload。"""

    payload: dict[str, object] = {
        "transport": "usb-uvc",
        "session_handle": entry.session_handle,
        "source_kind": entry.source_kind,
        "backend_preference": entry.backend_preference,
        "opened_at": entry.opened_at,
        "successful_reads_total": entry.successful_reads_total,
    }
    if entry.device_index is not None:
        payload["device_index"] = entry.device_index
    if entry.device_path is not None:
        payload["device_path"] = entry.device_path
    if entry.backend_name is not None:
        payload["backend_name"] = entry.backend_name
    if entry.requested_width is not None:
        payload["requested_width"] = entry.requested_width
    if entry.requested_height is not None:
        payload["requested_height"] = entry.requested_height
    if entry.requested_fps is not None:
        payload["requested_fps"] = round(float(entry.requested_fps), 4)
    if entry.last_read_at is not None:
        payload["last_read_at"] = entry.last_read_at
    if entry.last_frame_width is not None:
        payload["last_frame_width"] = entry.last_frame_width
    if entry.last_frame_height is not None:
        payload["last_frame_height"] = entry.last_frame_height
    if entry.last_frame_channels is not None:
        payload["last_frame_channels"] = entry.last_frame_channels
    return payload


def build_camera_session_summary(entry: UsbCameraSessionEntry, *, operation: str) -> dict[str, object]:
    """构造相机会话摘要对象。"""

    summary: dict[str, object] = {
        "transport": "usb-uvc",
        "operation": operation,
        "session_handle": entry.session_handle,
        "source_kind": entry.source_kind,
        "backend_preference": entry.backend_preference,
        "opened_at": entry.opened_at,
        "successful_reads_total": entry.successful_reads_total,
    }
    if entry.device_index is not None:
        summary["device_index"] = entry.device_index
    if entry.device_path is not None:
        summary["device_path"] = entry.device_path
    if entry.backend_name is not None:
        summary["backend_name"] = entry.backend_name
    if entry.requested_width is not None:
        summary["requested_width"] = entry.requested_width
    if entry.requested_height is not None:
        summary["requested_height"] = entry.requested_height
    if entry.requested_fps is not None:
        summary["requested_fps"] = round(float(entry.requested_fps), 4)
    if entry.last_read_at is not None:
        summary["last_read_at"] = entry.last_read_at
    if entry.last_frame_width is not None:
        summary["last_frame_width"] = entry.last_frame_width
    if entry.last_frame_height is not None:
        summary["last_frame_height"] = entry.last_frame_height
    if entry.last_frame_channels is not None:
        summary["last_frame_channels"] = entry.last_frame_channels
    return summary


def update_camera_session_read_state(
    entry: UsbCameraSessionEntry,
    *,
    frame: object,
    successful_reads: int,
) -> tuple[int, int, int]:
    """把一次读帧结果回写到会话条目。"""

    frame_width, frame_height, channels = get_frame_dimensions(frame)
    entry.successful_reads_total += int(successful_reads)
    entry.last_read_at = _now_isoformat()
    entry.last_frame_width = frame_width
    entry.last_frame_height = frame_height
    entry.last_frame_channels = channels
    return frame_width, frame_height, channels


def read_session_capture_observation(entry: UsbCameraSessionEntry, *, cv2_module: Any) -> dict[str, object]:
    """读取当前相机会话可观测到的宽高和帧率。"""

    observed_width = read_capture_property(
        entry.capture,
        property_id=int(cv2_module.CAP_PROP_FRAME_WIDTH),
    )
    observed_height = read_capture_property(
        entry.capture,
        property_id=int(cv2_module.CAP_PROP_FRAME_HEIGHT),
    )
    observed_fps = read_capture_property(
        entry.capture,
        property_id=int(cv2_module.CAP_PROP_FPS),
    )
    observation: dict[str, object] = {}
    if observed_width is not None:
        observation["observed_width"] = int(round(observed_width))
    if observed_height is not None:
        observation["observed_height"] = int(round(observed_height))
    if observed_fps is not None:
        observation["observed_fps"] = observed_fps
    return observation


def get_camera_session_parameter_values(
    entry: UsbCameraSessionEntry,
    *,
    parameter_names: tuple[str, ...],
    cv2_module: Any,
) -> dict[str, object]:
    """读取当前相机会话的一组参数值。"""

    parameter_values: dict[str, object] = {}
    for parameter_name in parameter_names:
        parameter_values[parameter_name] = read_camera_session_parameter(
            entry,
            parameter_name=parameter_name,
            cv2_module=cv2_module,
        )
    return parameter_values


def read_camera_session_parameter(
    entry: UsbCameraSessionEntry,
    *,
    parameter_name: str,
    cv2_module: Any,
) -> object:
    """读取单个相机会话参数。"""

    normalized_parameter_name = require_supported_parameter_name(parameter_name)
    if normalized_parameter_name == "session_handle":
        return entry.session_handle
    if normalized_parameter_name == "source_kind":
        return entry.source_kind
    if normalized_parameter_name == "device_index":
        return entry.device_index
    if normalized_parameter_name == "device_path":
        return entry.device_path
    if normalized_parameter_name == "backend_preference":
        return entry.backend_preference
    if normalized_parameter_name == "backend_name":
        return entry.backend_name or get_capture_backend_name(entry.capture)
    if normalized_parameter_name == "requested_width":
        return entry.requested_width
    if normalized_parameter_name == "requested_height":
        return entry.requested_height
    if normalized_parameter_name == "requested_fps":
        return round(float(entry.requested_fps), 4) if entry.requested_fps is not None else None
    if normalized_parameter_name == "opened_at":
        return entry.opened_at
    if normalized_parameter_name == "last_read_at":
        return entry.last_read_at
    if normalized_parameter_name == "successful_reads_total":
        return entry.successful_reads_total
    if normalized_parameter_name == "last_frame_width":
        return entry.last_frame_width
    if normalized_parameter_name == "last_frame_height":
        return entry.last_frame_height
    if normalized_parameter_name == "last_frame_channels":
        return entry.last_frame_channels

    parameter_spec = CAMERA_PARAMETER_SPECS[normalized_parameter_name]
    property_id = require_camera_property_id(
        parameter_name=normalized_parameter_name,
        parameter_spec=parameter_spec,
        cv2_module=cv2_module,
    )
    raw_value = read_capture_property(entry.capture, property_id=property_id)
    return normalize_camera_parameter_output(
        raw_value,
        value_kind=parameter_spec.value_kind,
    )


def set_camera_session_parameter_values(
    entry: UsbCameraSessionEntry,
    *,
    parameter_values: dict[str, object],
    verify_after_set: bool,
    cv2_module: Any,
) -> tuple[dict[str, object], dict[str, object]]:
    """批量写入当前相机会话参数，并返回请求值与观测值。"""

    if not parameter_values:
        raise InvalidRequestError("parameter_values 不能为空")

    requested_values: dict[str, object] = {}
    observed_values: dict[str, object] = {}
    for parameter_name, raw_value in parameter_values.items():
        normalized_parameter_name = require_supported_parameter_name(parameter_name)
        if normalized_parameter_name not in CAMERA_PARAMETER_SPECS:
            raise InvalidRequestError(
                "当前节点不支持写入指定相机参数",
                details={"parameter_name": normalized_parameter_name},
            )
        parameter_spec = CAMERA_PARAMETER_SPECS[normalized_parameter_name]
        if not parameter_spec.writable:
            raise InvalidRequestError(
                "当前节点不支持写入只读相机参数",
                details={"parameter_name": normalized_parameter_name},
            )
        property_id = require_camera_property_id(
            parameter_name=normalized_parameter_name,
            parameter_spec=parameter_spec,
            cv2_module=cv2_module,
        )
        normalized_write_value = normalize_camera_parameter_write_value(
            raw_value,
            value_kind=parameter_spec.value_kind,
            parameter_name=normalized_parameter_name,
        )
        _safe_capture_set(entry.capture, property_id=property_id, value=normalized_write_value)
        requested_values[normalized_parameter_name] = normalize_camera_parameter_output(
            normalized_write_value,
            value_kind=parameter_spec.value_kind,
        )
        _apply_requested_value_to_session_entry(
            entry,
            parameter_name=normalized_parameter_name,
            normalized_value=normalized_write_value,
        )
        if verify_after_set:
            observed_values[normalized_parameter_name] = read_camera_session_parameter(
                entry,
                parameter_name=normalized_parameter_name,
                cv2_module=cv2_module,
            )
    return requested_values, observed_values


def require_camera_property_id(
    *,
    parameter_name: str,
    parameter_spec: UsbCameraParameterSpec,
    cv2_module: Any,
) -> int:
    """解析单个相机参数在当前 OpenCV 运行时中的 property id。"""

    if not hasattr(cv2_module, parameter_spec.constant_name):
        raise InvalidRequestError(
            "当前 OpenCV 运行环境不支持指定相机参数",
            details={
                "parameter_name": parameter_name,
                "opencv_constant": parameter_spec.constant_name,
            },
        )
    return int(getattr(cv2_module, parameter_spec.constant_name))


def normalize_camera_parameter_output(raw_value: object, *, value_kind: str) -> object:
    """把底层 OpenCV 数值规范化成对外 JSON 值。"""

    if raw_value is None:
        return None
    if value_kind == "int":
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            return int(round(float(raw_value)))
        return None
    if value_kind == "bool":
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            return bool(round(float(raw_value)))
        return None
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        return round(float(raw_value), 4)
    return None


def normalize_camera_parameter_write_value(
    raw_value: object,
    *,
    value_kind: str,
    parameter_name: str,
) -> float:
    """把写入参数值规范化为 OpenCV set 所需的 float。"""

    if value_kind == "int":
        return float(require_positive_or_zero_number(raw_value, field_name=parameter_name, integer_only=True))
    if value_kind == "bool":
        if not isinstance(raw_value, bool):
            raise InvalidRequestError(f"{parameter_name} 必须是布尔值")
        return 1.0 if raw_value else 0.0
    return float(require_number(raw_value, field_name=parameter_name))


def _apply_requested_value_to_session_entry(
    entry: UsbCameraSessionEntry,
    *,
    parameter_name: str,
    normalized_value: float,
) -> None:
    """把刚写入的参数同步回会话条目中的请求摘要。"""

    if parameter_name == "width":
        entry.requested_width = int(round(normalized_value))
    elif parameter_name == "height":
        entry.requested_height = int(round(normalized_value))
    elif parameter_name == "fps":
        entry.requested_fps = float(normalized_value)


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
    if not math.isfinite(float(value)):
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


def require_parameter_name_list(raw_value: object) -> list[str]:
    """把输入解析为参数名列表。"""

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError("parameter_names 必须是非空数组")
    return [require_supported_parameter_name(item) for item in raw_value]


def require_parameter_value_mapping(raw_value: object) -> dict[str, object]:
    """把输入解析为参数写入对象。"""

    if not isinstance(raw_value, dict) or not raw_value:
        raise InvalidRequestError("parameter_values 必须是非空对象")
    normalized_mapping: dict[str, object] = {}
    for key, value in raw_value.items():
        normalized_mapping[require_supported_parameter_name(key)] = value
    return normalized_mapping


def require_supported_parameter_name(raw_value: object) -> str:
    """校验相机参数名是否在支持列表中。"""

    normalized_name = require_string(raw_value, field_name="parameter_name")
    if normalized_name not in CAMERA_PARAMETER_NAME_VALUES:
        raise InvalidRequestError(
            "当前节点不支持指定相机参数名",
            details={"parameter_name": normalized_name, "allowed_values": list(CAMERA_PARAMETER_NAME_VALUES)},
        )
    return normalized_name


def require_number(raw_value: object, *, field_name: str) -> float:
    """把输入解析为有限数值。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    normalized_value = float(raw_value)
    if not math.isfinite(normalized_value):
        raise InvalidRequestError(f"{field_name} 必须是有限数值")
    return normalized_value


def require_positive_or_zero_number(
    raw_value: object,
    *,
    field_name: str,
    integer_only: bool = False,
) -> int | float:
    """把输入解析为非负数。"""

    if integer_only:
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise InvalidRequestError(f"{field_name} 必须是整数")
        if raw_value < 0:
            raise InvalidRequestError(f"{field_name} 不能小于 0")
        return int(raw_value)
    normalized_value = require_number(raw_value, field_name=field_name)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


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


def _now_isoformat() -> str:
    """返回 UTC ISO8601 时间字符串。"""

    return datetime.now(timezone.utc).isoformat()
