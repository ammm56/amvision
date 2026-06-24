"""USB / UVC 相机会话参数读写。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.capture import (
    get_capture_backend_name,
    read_capture_property,
    safe_capture_set,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.payloads import build_camera_session_stream_state_payload
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.types import (
    CAMERA_PARAMETER_SPECS,
    UsbCameraParameterSpec,
    UsbCameraSessionEntry,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.validators import (
    require_number,
    require_positive_or_zero_number,
    require_supported_parameter_name,
)


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
        with entry.capture_lock:
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
    if normalized_parameter_name == "stream_active":
        return build_camera_session_stream_state_payload(entry)["stream_active"]
    if normalized_parameter_name == "stream_worker_alive":
        return build_camera_session_stream_state_payload(entry)["stream_worker_alive"]
    if normalized_parameter_name == "stream_started_at":
        return build_camera_session_stream_state_payload(entry).get("stream_started_at")
    if normalized_parameter_name == "stream_buffer_capacity":
        return build_camera_session_stream_state_payload(entry)["stream_buffer_capacity"]
    if normalized_parameter_name == "stream_buffer_count":
        return build_camera_session_stream_state_payload(entry)["stream_buffer_count"]
    if normalized_parameter_name == "stream_target_fps":
        return build_camera_session_stream_state_payload(entry).get("stream_target_fps")
    if normalized_parameter_name == "stream_failure_retry_delay_ms":
        return build_camera_session_stream_state_payload(entry)["stream_failure_retry_delay_ms"]
    if normalized_parameter_name == "stream_last_frame_index":
        return build_camera_session_stream_state_payload(entry).get("stream_last_frame_index")
    if normalized_parameter_name == "stream_last_timestamp_ms":
        return build_camera_session_stream_state_payload(entry).get("stream_last_timestamp_ms")
    if normalized_parameter_name == "stream_last_error":
        return build_camera_session_stream_state_payload(entry).get("stream_last_error")

    parameter_spec = CAMERA_PARAMETER_SPECS[normalized_parameter_name]
    property_id = require_camera_property_id(
        parameter_name=normalized_parameter_name,
        parameter_spec=parameter_spec,
        cv2_module=cv2_module,
    )
    with entry.capture_lock:
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
        with entry.capture_lock:
            safe_capture_set(entry.capture, property_id=property_id, value=normalized_write_value)
        requested_values[normalized_parameter_name] = normalize_camera_parameter_output(
            normalized_write_value,
            value_kind=parameter_spec.value_kind,
        )
        apply_requested_value_to_session_entry(
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


def apply_requested_value_to_session_entry(
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
