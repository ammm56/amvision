"""USB / UVC 相机会话关闭节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime import sessions
from custom_nodes.camera_usb_uvc_nodes.specs import CLOSE_DEVICE_NODE_TYPE_ID


NODE_TYPE_ID = CLOSE_DEVICE_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """关闭一个已打开的 USB / UVC 相机会话。"""

    return {"result": sessions.close_camera_session(request)}
