"""USB / UVC 相机 runtime 类型和常量。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Condition, Event, RLock, Thread


BACKEND_PREFERENCE_VALUES: tuple[str, ...] = (
    "any",
    "dshow",
    "msmf",
    "v4l2",
    "gstreamer",
)
OUTPUT_FORMAT_VALUES: tuple[str, ...] = ("png", "jpeg")
STREAM_SAMPLE_MODE_VALUES: tuple[str, ...] = ("tail", "head", "uniform")
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
            "stream_active",
            "stream_worker_alive",
            "stream_started_at",
            "stream_buffer_capacity",
            "stream_buffer_count",
            "stream_target_fps",
            "stream_failure_retry_delay_ms",
            "stream_last_frame_index",
            "stream_last_timestamp_ms",
            "stream_last_error",
        )
    )
)
DEFAULT_CAMERA_PARAMETER_NAMES: tuple[str, ...] = (
    "width",
    "height",
    "fps",
    "backend_name",
)


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
class UsbCameraStartStreamConfig:
    """描述 start-stream 节点的最终运行配置。"""

    buffer_capacity: int
    target_fps: float | None
    failure_retry_delay_ms: int
    restart_if_active: bool


@dataclass(frozen=True)
class UsbCameraReadWindowConfig:
    """描述 read-window 节点的最终运行配置。"""

    max_frames: int
    sample_mode: str
    wait_for_min_frames: int
    wait_timeout_seconds: float
    output_format: str
    jpeg_quality: int


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
class UsbCameraBufferedFrame:
    """描述一帧保存在内存环形缓冲中的图像。"""

    frame_index: int
    timestamp_ms: float
    frame: object
    width: int
    height: int
    channels: int
    captured_at: str


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
    capture_lock: RLock = field(default_factory=RLock, repr=False)
    stream_state_lock: RLock = field(default_factory=RLock, repr=False)
    stream_condition: Condition = field(init=False, repr=False)
    stream_thread: Thread | None = field(default=None, repr=False)
    stream_stop_event: Event | None = field(default=None, repr=False)
    stream_buffer: deque[UsbCameraBufferedFrame] = field(default_factory=deque, repr=False)
    stream_active: bool = False
    stream_started_at: str | None = None
    stream_started_monotonic: float | None = None
    stream_buffer_capacity: int = 0
    stream_target_fps: float | None = None
    stream_failure_retry_delay_ms: int = 50
    stream_last_frame_index: int | None = None
    stream_last_timestamp_ms: float | None = None
    stream_last_error: str | None = None

    def __post_init__(self) -> None:
        """初始化与流线程共享的条件变量。"""

        self.stream_condition = Condition(self.stream_state_lock)
