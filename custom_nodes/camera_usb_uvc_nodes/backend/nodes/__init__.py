"""USB / UVC 相机节点模块集合。"""

from __future__ import annotations

from custom_nodes.camera_usb_uvc_nodes.backend.nodes.capture_frame import (
    NODE_TYPE_ID as CAPTURE_FRAME_NODE_TYPE_ID,
    handle_node as capture_frame_handler,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes.enumerate_devices import (
    NODE_TYPE_ID as ENUMERATE_DEVICES_NODE_TYPE_ID,
    handle_node as enumerate_devices_handler,
)


NODE_HANDLERS = {
    ENUMERATE_DEVICES_NODE_TYPE_ID: enumerate_devices_handler,
    CAPTURE_FRAME_NODE_TYPE_ID: capture_frame_handler,
}


__all__ = ["NODE_HANDLERS"]

