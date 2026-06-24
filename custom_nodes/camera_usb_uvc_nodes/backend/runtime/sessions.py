"""USB / UVC 相机会话生命周期管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.capture import (
    configure_video_capture,
    get_capture_backend_name,
    open_video_capture_or_raise,
    read_capture_property,
    read_last_frame,
    safe_release_capture,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.payloads import (
    build_camera_session_summary,
    build_value_payload,
    require_camera_session_payload,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.streaming import (
    is_camera_session_stream_active,
    stop_camera_session_stream,
    update_camera_session_read_state,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.types import (
    CAMERA_SESSION_REGISTRY_METADATA_KEY,
    UsbCameraOpenConfig,
    UsbCameraSessionEntry,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.validators import now_isoformat, require_string


_RUNTIME_CAMERA_SESSION_REGISTRIES: WeakKeyDictionary[object, UsbCameraSessionRegistry] = WeakKeyDictionary()
_RUNTIME_CAMERA_SESSION_REGISTRIES_LOCK = Lock()


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
            stop_camera_session_stream(entry, clear_buffer=True)
            safe_release_capture(entry.capture)


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

    video_capture = open_video_capture_or_raise(
        source=config.source_value,
        api_preference=config.api_preference,
        backend_preference=config.backend_preference,
        node_id=request.node_id,
    )
    try:
        configure_video_capture(
            video_capture,
            width=config.width,
            height=config.height,
            fps=config.fps,
            cv2_module=cv2_module,
        )
        entry = UsbCameraSessionEntry(
            session_handle=f"usb-camera-session-{uuid4().hex}",
            capture=video_capture,
            source_kind=config.source_kind,
            device_index=config.device_index,
            device_path=config.device_path,
            backend_preference=config.backend_preference,
            api_preference=config.api_preference,
            opened_at=now_isoformat(),
            requested_width=config.width,
            requested_height=config.height,
            requested_fps=config.fps,
            backend_name=get_capture_backend_name(video_capture),
        )
        summary = build_camera_session_summary(entry, operation="open_device")
        summary["probe_frame"] = config.probe_frame
        if config.probe_frame:
            frame, successful_reads = read_last_frame(
                video_capture,
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
        safe_release_capture(video_capture)
        raise


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

    stream_was_active = is_camera_session_stream_active(entry)
    stop_camera_session_stream(entry, clear_buffer=True)
    summary = build_camera_session_summary(entry, operation="close_device")
    summary["closed"] = True
    summary["stream_was_active"] = stream_was_active
    safe_release_capture(entry.capture)
    return build_value_payload(summary)


def read_session_capture_observation(entry: UsbCameraSessionEntry, *, cv2_module: Any) -> dict[str, object]:
    """读取当前相机会话可观测到的宽高和帧率。"""

    with entry.capture_lock:
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
