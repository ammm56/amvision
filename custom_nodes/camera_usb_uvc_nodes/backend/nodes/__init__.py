"""USB / UVC 相机节点模块集合。"""

from __future__ import annotations

from custom_nodes.camera_usb_uvc_nodes.backend.nodes.capture_frame import (
    NODE_TYPE_ID as CAPTURE_FRAME_NODE_TYPE_ID,
    handle_node as capture_frame_handler,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes.close_device import (
    NODE_TYPE_ID as CLOSE_DEVICE_NODE_TYPE_ID,
    handle_node as close_device_handler,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes.enumerate_devices import (
    NODE_TYPE_ID as ENUMERATE_DEVICES_NODE_TYPE_ID,
    handle_node as enumerate_devices_handler,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes.get_parameter import (
    NODE_TYPE_ID as GET_PARAMETER_NODE_TYPE_ID,
    handle_node as get_parameter_handler,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes.open_device import (
    NODE_TYPE_ID as OPEN_DEVICE_NODE_TYPE_ID,
    handle_node as open_device_handler,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes.read_latest_frame import (
    NODE_TYPE_ID as READ_LATEST_FRAME_NODE_TYPE_ID,
    handle_node as read_latest_frame_handler,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes.set_parameter import (
    NODE_TYPE_ID as SET_PARAMETER_NODE_TYPE_ID,
    handle_node as set_parameter_handler,
)


NODE_HANDLERS = {
    ENUMERATE_DEVICES_NODE_TYPE_ID: enumerate_devices_handler,
    CAPTURE_FRAME_NODE_TYPE_ID: capture_frame_handler,
    OPEN_DEVICE_NODE_TYPE_ID: open_device_handler,
    READ_LATEST_FRAME_NODE_TYPE_ID: read_latest_frame_handler,
    GET_PARAMETER_NODE_TYPE_ID: get_parameter_handler,
    SET_PARAMETER_NODE_TYPE_ID: set_parameter_handler,
    CLOSE_DEVICE_NODE_TYPE_ID: close_device_handler,
}


__all__ = ["NODE_HANDLERS"]
