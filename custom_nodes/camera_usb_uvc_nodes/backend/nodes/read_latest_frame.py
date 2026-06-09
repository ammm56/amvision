"""USB / UVC 相机会话读帧节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend import support
from custom_nodes.camera_usb_uvc_nodes.specs import READ_LATEST_FRAME_NODE_TYPE_ID


NODE_TYPE_ID = READ_LATEST_FRAME_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从已打开的 USB / UVC 相机会话读取最新单帧。"""

    cv2_module, _ = support.require_opencv_imports()
    _session_payload, session_entry = support.require_camera_session_entry(request)
    config = support.resolve_session_read_config(request)
    frame, successful_reads = support.read_last_frame(
        session_entry.capture,
        warmup_frame_count=config.warmup_frame_count,
        retry_read_count=config.retry_read_count,
        node_id=request.node_id,
        source_details={"session_handle": session_entry.session_handle},
    )
    frame_width, frame_height, channels = support.update_camera_session_read_state(
        session_entry,
        frame=frame,
        successful_reads=successful_reads,
    )
    encoded_frame, media_type = support.encode_frame_bytes(
        frame=frame,
        output_format=config.output_format,
        jpeg_quality=config.jpeg_quality,
        cv2_module=cv2_module,
    )
    image_payload = support.build_captured_image_payload(
        request,
        content=encoded_frame,
        media_type=media_type,
        width=frame_width,
        height=frame_height,
        output_object_key=config.output_object_key,
        overwrite=config.overwrite,
    )
    summary = support.build_camera_session_summary(
        session_entry,
        operation="read_latest_frame",
    )
    summary.update(
        {
            "successful_reads": successful_reads,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "channels": channels,
            "output_format": config.output_format,
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
    summary.update(support.read_session_capture_observation(session_entry, cv2_module=cv2_module))
    return {
        "session": support.build_camera_session_payload(session_entry),
        "image": image_payload,
        "summary": support.build_value_payload(summary),
    }
