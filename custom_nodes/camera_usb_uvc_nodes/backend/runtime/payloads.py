"""USB / UVC 相机 runtime payload 构造。"""

from __future__ import annotations

from backend.nodes.runtime_support import copy_image_payload, register_image_bytes
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.types import UsbCameraSessionEntry
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.validators import (
    normalize_json_safe_value,
    require_string,
)


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


def build_value_payload(value: object) -> dict[str, object]:
    """把 JSON 安全值包装成 value.v1。"""

    return {"value": normalize_json_safe_value(value)}


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
    ):
        if key in payload:
            normalized_payload[key] = normalize_json_safe_value(payload[key])
    return normalized_payload


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
    payload.update(build_camera_session_stream_state_payload(entry))
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
    summary.update(build_camera_session_stream_state_payload(entry))
    return summary


def build_camera_session_stream_state_payload(entry: UsbCameraSessionEntry) -> dict[str, object]:
    """构造对外可见的流状态字段。"""

    with entry.stream_condition:
        stream_state: dict[str, object] = {
            "stream_active": bool(
                entry.stream_active
                and entry.stream_thread is not None
                and entry.stream_thread.is_alive()
                and entry.stream_stop_event is not None
                and not entry.stream_stop_event.is_set()
            ),
            "stream_worker_alive": bool(entry.stream_thread is not None and entry.stream_thread.is_alive()),
            "stream_buffer_count": len(entry.stream_buffer),
            "stream_buffer_capacity": entry.stream_buffer_capacity,
            "stream_failure_retry_delay_ms": entry.stream_failure_retry_delay_ms,
        }
        if entry.stream_started_at is not None:
            stream_state["stream_started_at"] = entry.stream_started_at
        if entry.stream_target_fps is not None:
            stream_state["stream_target_fps"] = round(float(entry.stream_target_fps), 4)
        if entry.stream_last_frame_index is not None:
            stream_state["stream_last_frame_index"] = entry.stream_last_frame_index
        if entry.stream_last_timestamp_ms is not None:
            stream_state["stream_last_timestamp_ms"] = round(float(entry.stream_last_timestamp_ms), 4)
        if entry.stream_last_error is not None:
            stream_state["stream_last_error"] = entry.stream_last_error
        return stream_state
