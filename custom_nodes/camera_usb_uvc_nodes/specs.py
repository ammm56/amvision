"""USB / UVC 相机节点包规格常量。"""

from __future__ import annotations


NODE_PACK_ID = "camera.usb-uvc-nodes"
NODE_PACK_VERSION = "0.1.0"

CAMERA_SESSION_PAYLOAD_TYPE_ID = "camera-session.v1"
ENUMERATE_DEVICES_NODE_TYPE_ID = "custom.camera.usb.enumerate-devices"
CAPTURE_FRAME_NODE_TYPE_ID = "custom.camera.usb.capture-frame"
OPEN_DEVICE_NODE_TYPE_ID = "custom.camera.usb.open-device"
START_STREAM_NODE_TYPE_ID = "custom.camera.usb.start-stream"
READ_WINDOW_NODE_TYPE_ID = "custom.camera.usb.read-window"
READ_LATEST_FRAME_NODE_TYPE_ID = "custom.camera.usb.read-latest-frame"
GET_PARAMETER_NODE_TYPE_ID = "custom.camera.usb.get-parameter"
SET_PARAMETER_NODE_TYPE_ID = "custom.camera.usb.set-parameter"
CLOSE_DEVICE_NODE_TYPE_ID = "custom.camera.usb.close-device"

ALL_NODE_TYPE_IDS: tuple[str, ...] = (
    ENUMERATE_DEVICES_NODE_TYPE_ID,
    CAPTURE_FRAME_NODE_TYPE_ID,
    OPEN_DEVICE_NODE_TYPE_ID,
    START_STREAM_NODE_TYPE_ID,
    READ_WINDOW_NODE_TYPE_ID,
    READ_LATEST_FRAME_NODE_TYPE_ID,
    GET_PARAMETER_NODE_TYPE_ID,
    SET_PARAMETER_NODE_TYPE_ID,
    CLOSE_DEVICE_NODE_TYPE_ID,
)
