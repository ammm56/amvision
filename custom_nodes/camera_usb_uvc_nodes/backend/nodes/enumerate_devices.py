"""USB / UVC 相机枚举节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend import support
from custom_nodes.camera_usb_uvc_nodes.specs import ENUMERATE_DEVICES_NODE_TYPE_ID


NODE_TYPE_ID = ENUMERATE_DEVICES_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """探测一段设备索引范围内可打开的 USB / UVC 相机。"""

    cv2_module, _ = support.require_opencv_imports()
    config = support.resolve_enumerate_config(request, cv2_module=cv2_module)
    device_items: list[dict[str, object]] = []
    scanned_indices = list(range(config.start_index, config.start_index + config.device_count))

    for device_index in scanned_indices:
        capture = None
        try:
            capture = support.create_video_capture(
                source=device_index,
                api_preference=config.api_preference,
            )
            if capture is None or bool(capture.isOpened()) is not True:
                support.safe_release_capture(capture)
                continue

            device_item: dict[str, object] = {
                "device_index": device_index,
                "display_name": f"USB Camera {device_index}",
                "source_kind": "device-index",
                "backend_preference": config.backend_preference,
            }
            backend_name = support.get_capture_backend_name(capture)
            if backend_name is not None:
                device_item["backend_name"] = backend_name

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
            if observed_width is not None:
                device_item["observed_width"] = int(round(observed_width))
            if observed_height is not None:
                device_item["observed_height"] = int(round(observed_height))
            if observed_fps is not None:
                device_item["observed_fps"] = observed_fps

            if config.probe_frame:
                try:
                    frame, successful_reads = support.read_last_frame(
                        capture,
                        warmup_frame_count=config.warmup_frame_count,
                        retry_read_count=1,
                        node_id=request.node_id,
                        source_details={"device_index": device_index},
                    )
                    frame_width, frame_height, channels = support.get_frame_dimensions(frame)
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
            support.safe_release_capture(capture)

    return {
        "result": support.build_value_payload(
            {
                "transport": "usb-uvc",
                "operation": "enumerate_devices",
                "backend_preference": config.backend_preference,
                "start_index": config.start_index,
                "device_count": config.device_count,
                "probe_frame": config.probe_frame,
                "scanned_indices": scanned_indices,
                "found_count": len(device_items),
                "items": device_items,
            }
        )
    }

