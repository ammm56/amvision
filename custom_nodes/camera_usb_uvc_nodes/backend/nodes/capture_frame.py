"""USB / UVC 相机单帧采集节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend import support
from custom_nodes.camera_usb_uvc_nodes.specs import CAPTURE_FRAME_NODE_TYPE_ID


NODE_TYPE_ID = CAPTURE_FRAME_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从指定 USB / UVC 相机采集单帧，并输出 image-ref。"""

    cv2_module, _ = support.require_opencv_imports()
    config = support.resolve_capture_config(request, cv2_module=cv2_module)
    capture = support.open_video_capture_or_raise(
        source=config.source_value,
        api_preference=config.api_preference,
        backend_preference=config.backend_preference,
        node_id=request.node_id,
    )
    try:
        support.configure_video_capture(
            capture,
            width=config.width,
            height=config.height,
            fps=config.fps,
            cv2_module=cv2_module,
        )
        frame, successful_reads = support.read_last_frame(
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
        frame_width, frame_height, channels = support.get_frame_dimensions(frame)
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
        backend_name = support.get_capture_backend_name(capture)
        observed_width = support.read_capture_property(
            capture,
            property_id=int(cv2_module.CAP_PROP_FRAME_WIDTH),
        )
        observed_height = support.read_capture_property(
            capture,
            property_id=int(cv2_module.CAP_PROP_FRAME_HEIGHT),
        )
        observed_fps = support.read_capture_property(
            capture,
            property_id=int(cv2_module.CAP_PROP_FPS),
        )
        summary: dict[str, object] = {
            "transport": "usb-uvc",
            "operation": "capture_frame",
            "source_kind": config.source_kind,
            "backend_preference": config.backend_preference,
            "output_format": config.output_format,
            "media_type": media_type,
            "successful_reads": successful_reads,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "channels": channels,
            "transport_kind": image_payload.get("transport_kind"),
        }
        if config.device_index is not None:
            summary["device_index"] = config.device_index
        if config.device_path is not None:
            summary["device_path"] = config.device_path
        if config.width is not None:
            summary["requested_width"] = config.width
        if config.height is not None:
            summary["requested_height"] = config.height
        if config.fps is not None:
            summary["requested_fps"] = config.fps
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
            "summary": support.build_value_payload(summary),
        }
    finally:
        support.safe_release_capture(capture)
