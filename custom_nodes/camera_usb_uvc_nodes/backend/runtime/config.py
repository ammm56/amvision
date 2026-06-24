"""USB / UVC 相机节点参数解析。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.types import (
    BACKEND_PREFERENCE_VALUES,
    DEFAULT_CAMERA_PARAMETER_NAMES,
    OUTPUT_FORMAT_VALUES,
    STREAM_SAMPLE_MODE_VALUES,
    UsbCameraCaptureConfig,
    UsbCameraEnumerateConfig,
    UsbCameraGetParametersConfig,
    UsbCameraOpenConfig,
    UsbCameraReadWindowConfig,
    UsbCameraSessionReadConfig,
    UsbCameraSetParametersConfig,
    UsbCameraStartStreamConfig,
)
from custom_nodes.camera_usb_uvc_nodes.backend.runtime.validators import (
    normalize_optional_text,
    require_bool,
    require_non_negative_int,
    require_optional_positive_float,
    require_optional_positive_int,
    require_optional_request_object,
    require_parameter_name_list,
    require_parameter_value_mapping,
    require_positive_int,
    require_positive_or_zero_number,
    require_string,
    require_uint8_range,
)


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


def resolve_start_stream_config(request: WorkflowNodeExecutionRequest) -> UsbCameraStartStreamConfig:
    """从节点参数与可选 request 输入解析 start-stream 配置。"""

    request_override = require_optional_request_object(request.input_values.get("request"))
    target_fps_value = request_override.get("target_fps", request.parameters.get("target_fps"))
    return UsbCameraStartStreamConfig(
        buffer_capacity=require_positive_int(
            request_override.get("buffer_capacity", request.parameters.get("buffer_capacity", 16)),
            field_name="buffer_capacity",
        ),
        target_fps=require_optional_positive_float(target_fps_value, field_name="target_fps"),
        failure_retry_delay_ms=require_non_negative_int(
            request_override.get(
                "failure_retry_delay_ms",
                request.parameters.get("failure_retry_delay_ms", 50),
            ),
            field_name="failure_retry_delay_ms",
        ),
        restart_if_active=require_bool(
            request_override.get(
                "restart_if_active",
                request.parameters.get("restart_if_active", False),
            ),
            field_name="restart_if_active",
        ),
    )


def resolve_read_window_config(request: WorkflowNodeExecutionRequest) -> UsbCameraReadWindowConfig:
    """从节点参数与可选 request 输入解析 read-window 配置。"""

    request_override = require_optional_request_object(request.input_values.get("request"))
    sample_mode = require_string(
        request_override.get("sample_mode", request.parameters.get("sample_mode", "tail")),
        field_name="sample_mode",
    ).lower()
    if sample_mode not in STREAM_SAMPLE_MODE_VALUES:
        raise InvalidRequestError(
            "sample_mode 不在支持列表中",
            details={"allowed_values": list(STREAM_SAMPLE_MODE_VALUES)},
        )
    wait_timeout_raw = request_override.get(
        "wait_timeout_seconds",
        request.parameters.get("wait_timeout_seconds", 1.0),
    )
    return UsbCameraReadWindowConfig(
        max_frames=require_positive_int(
            request_override.get("max_frames", request.parameters.get("max_frames", 8)),
            field_name="max_frames",
        ),
        sample_mode=sample_mode,
        wait_for_min_frames=require_positive_int(
            request_override.get(
                "wait_for_min_frames",
                request.parameters.get("wait_for_min_frames", 1),
            ),
            field_name="wait_for_min_frames",
        ),
        wait_timeout_seconds=float(
            require_positive_or_zero_number(
                wait_timeout_raw,
                field_name="wait_timeout_seconds",
            )
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
