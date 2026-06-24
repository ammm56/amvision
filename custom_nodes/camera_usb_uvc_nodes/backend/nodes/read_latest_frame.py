"""USB / UVC 相机会话读帧节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime import capture, config, payloads, sessions, streaming
from custom_nodes.camera_usb_uvc_nodes.specs import READ_LATEST_FRAME_NODE_TYPE_ID


NODE_TYPE_ID = READ_LATEST_FRAME_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从已打开的 USB / UVC 相机会话读取最新单帧。"""

    cv2_module, _ = capture.require_opencv_imports()
    _session_payload, session_entry = sessions.require_camera_session_entry(request)
    read_config = config.resolve_session_read_config(request)
    frame, successful_reads, from_stream_buffer = streaming.read_camera_session_latest_frame(
        request,
        entry=session_entry,
        config=read_config,
    )
    if from_stream_buffer:
        frame_width, frame_height, channels = capture.get_frame_dimensions(frame)
    else:
        frame_width, frame_height, channels = streaming.update_camera_session_read_state(
            session_entry,
            frame=frame,
            successful_reads=successful_reads,
        )
    encoded_frame, media_type = capture.encode_frame_bytes(
        frame=frame,
        output_format=read_config.output_format,
        jpeg_quality=read_config.jpeg_quality,
        cv2_module=cv2_module,
    )
    image_payload = payloads.build_captured_image_payload(
        request,
        content=encoded_frame,
        media_type=media_type,
        width=frame_width,
        height=frame_height,
        output_object_key=read_config.output_object_key,
        overwrite=read_config.overwrite,
    )
    summary = payloads.build_camera_session_summary(
        session_entry,
        operation="read_latest_frame",
    )
    summary.update(
        {
            "successful_reads": successful_reads,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "channels": channels,
            "from_stream_buffer": from_stream_buffer,
            "output_format": read_config.output_format,
            "media_type": media_type,
            "transport_kind": image_payload.get("transport_kind"),
        }
    )
    output_object_key = image_payload.get("object_key")
    if isinstance(output_object_key, str) and output_object_key:
        summary["output_object_key"] = output_object_key
    image_handle = image_payload.get("image_handle")
    if isinstance(image_handle, str) and image_handle:
        summary["image_handle"] = image_handle
    summary.update(sessions.read_session_capture_observation(session_entry, cv2_module=cv2_module))
    return {
        "session": payloads.build_camera_session_payload(session_entry),
        "image": image_payload,
        "summary": payloads.build_value_payload(summary),
    }
