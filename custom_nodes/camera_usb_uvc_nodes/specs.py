"""USB / UVC 相机节点包规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "camera.usb-uvc-nodes"
NODE_PACK_VERSION = "0.1.0"

ENUMERATE_DEVICES_NODE_TYPE_ID = "custom.camera.usb.enumerate-devices"
CAPTURE_FRAME_NODE_TYPE_ID = "custom.camera.usb.capture-frame"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (
    ENUMERATE_DEVICES_NODE_TYPE_ID,
    CAPTURE_FRAME_NODE_TYPE_ID,
)

