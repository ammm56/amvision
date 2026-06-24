"""USB / UVC 相机单帧采集节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime import capture, config, payloads
from custom_nodes.camera_usb_uvc_nodes.specs import CAPTURE_FRAME_NODE_TYPE_ID


NODE_TYPE_ID = CAPTURE_FRAME_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从指定 USB / UVC 相机采集单帧，并输出 image-ref。"""

    cv2_module, _ = capture.require_opencv_imports()
    capture_config = config.resolve_capture_config(request, cv2_module=cv2_module)
    video_capture = capture.open_video_capture_or_raise(
        source=capture_config.source_value,
        api_preference=capture_config.api_preference,
        backend_preference=capture_config.backend_preference,
        node_id=request.node_id,
    )
    try:
        capture.configure_video_capture(
            video_capture,
            width=capture_config.width,
            height=capture_config.height,
            fps=capture_config.fps,
            cv2_module=cv2_module,
        )
        frame, successful_reads = capture.read_last_frame(
            video_capture,
            warmup_frame_count=capture_config.warmup_frame_count,
            retry_read_count=capture_config.retry_read_count,
            node_id=request.node_id,
            source_details={
                "source_kind": capture_config.source_kind,
                "device_index": capture_config.device_index,
                "device_path": capture_config.device_path,
            },
        )
        frame_width, frame_height, channels = capture.get_frame_dimensions(frame)
        encoded_frame, media_type = capture.encode_frame_bytes(
            frame=frame,
            output_format=capture_config.output_format,
            jpeg_quality=capture_config.jpeg_quality,
            cv2_module=cv2_module,
        )
        image_payload = payloads.build_captured_image_payload(
            request,
            content=encoded_frame,
            media_type=media_type,
            width=frame_width,
            height=frame_height,
            output_object_key=capture_config.output_object_key,
            overwrite=capture_config.overwrite,
        )
        backend_name = capture.get_capture_backend_name(video_capture)
        observed_width = capture.read_capture_property(
            video_capture,
            property_id=int(cv2_module.CAP_PROP_FRAME_WIDTH),
        )
        observed_height = capture.read_capture_property(
            video_capture,
            property_id=int(cv2_module.CAP_PROP_FRAME_HEIGHT),
        )
        observed_fps = capture.read_capture_property(
            video_capture,
            property_id=int(cv2_module.CAP_PROP_FPS),
        )
        summary: dict[str, object] = {
            "transport": "usb-uvc",
            "operation": "capture_frame",
            "source_kind": capture_config.source_kind,
            "backend_preference": capture_config.backend_preference,
            "output_format": capture_config.output_format,
            "media_type": media_type,
            "successful_reads": successful_reads,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "channels": channels,
            "transport_kind": image_payload.get("transport_kind"),
        }
        if capture_config.device_index is not None:
            summary["device_index"] = capture_config.device_index
        if capture_config.device_path is not None:
            summary["device_path"] = capture_config.device_path
        if capture_config.width is not None:
            summary["requested_width"] = capture_config.width
        if capture_config.height is not None:
            summary["requested_height"] = capture_config.height
        if capture_config.fps is not None:
            summary["requested_fps"] = capture_config.fps
        if backend_name is not None:
            summary["backend_name"] = backend_name
        if observed_width is not None:
            summary["observed_width"] = int(round(observed_width))
        if observed_height is not None:
            summary["observed_height"] = int(round(observed_height))
        if observed_fps is not None:
            summary["observed_fps"] = observed_fps
        output_object_key = image_payload.get("object_key")
        if isinstance(output_object_key, str) and output_object_key:
            summary["output_object_key"] = output_object_key
        image_handle = image_payload.get("image_handle")
        if isinstance(image_handle, str) and image_handle:
            summary["image_handle"] = image_handle
        return {
            "image": image_payload,
            "summary": payloads.build_value_payload(summary),
        }
    finally:
        capture.safe_release_capture(video_capture)
