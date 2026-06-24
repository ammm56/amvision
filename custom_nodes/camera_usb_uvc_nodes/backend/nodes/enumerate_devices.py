"""USB / UVC 相机枚举节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime import capture, config, payloads
from custom_nodes.camera_usb_uvc_nodes.specs import ENUMERATE_DEVICES_NODE_TYPE_ID


NODE_TYPE_ID = ENUMERATE_DEVICES_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """探测一段设备索引范围内可打开的 USB / UVC 相机。"""

    cv2_module, _ = capture.require_opencv_imports()
    enumerate_config = config.resolve_enumerate_config(request, cv2_module=cv2_module)
    device_items: list[dict[str, object]] = []
    scanned_indices = list(range(enumerate_config.start_index, enumerate_config.start_index + enumerate_config.device_count))

    for device_index in scanned_indices:
        video_capture = None
        try:
            video_capture = capture.create_video_capture(
                source=device_index,
                api_preference=enumerate_config.api_preference,
            )
            if video_capture is None or bool(video_capture.isOpened()) is not True:
                capture.safe_release_capture(video_capture)
                continue

            device_item: dict[str, object] = {
                "device_index": device_index,
                "display_name": f"USB Camera {device_index}",
                "source_kind": "device-index",
                "backend_preference": enumerate_config.backend_preference,
            }
            backend_name = capture.get_capture_backend_name(video_capture)
            if backend_name is not None:
                device_item["backend_name"] = backend_name

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
            if observed_width is not None:
                device_item["observed_width"] = int(round(observed_width))
            if observed_height is not None:
                device_item["observed_height"] = int(round(observed_height))
            if observed_fps is not None:
                device_item["observed_fps"] = observed_fps

            if enumerate_config.probe_frame:
                try:
                    frame, successful_reads = capture.read_last_frame(
                        video_capture,
                        warmup_frame_count=enumerate_config.warmup_frame_count,
                        retry_read_count=1,
                        node_id=request.node_id,
                        source_details={"device_index": device_index},
                    )
                    frame_width, frame_height, channels = capture.get_frame_dimensions(frame)
                    device_item["probe_frame_success"] = True
                    device_item["successful_reads"] = successful_reads
                    device_item["observed_width"] = frame_width
                    device_item["observed_height"] = frame_height
                    device_item["channels"] = channels
                except Exception as error:
                    device_item["probe_frame_success"] = False
                    device_item["probe_error"] = str(error)
            device_items.append(device_item)
        finally:
            capture.safe_release_capture(video_capture)

    return {
        "result": payloads.build_value_payload(
            {
                "transport": "usb-uvc",
                "operation": "enumerate_devices",
                "backend_preference": enumerate_config.backend_preference,
                "start_index": enumerate_config.start_index,
                "device_count": enumerate_config.device_count,
                "probe_frame": enumerate_config.probe_frame,
                "scanned_indices": scanned_indices,
                "found_count": len(device_items),
                "items": device_items,
            }
        )
    }

