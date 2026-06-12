"""USB / UVC 相机打开节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend import support
from custom_nodes.camera_usb_uvc_nodes.specs import OPEN_DEVICE_NODE_TYPE_ID


NODE_TYPE_ID = OPEN_DEVICE_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """打开一个可跨节点复用的 USB / UVC 相机会话。"""

    cv2_module, _ = support.require_opencv_imports()
    config = support.resolve_open_config(request, cv2_module=cv2_module)
    session_entry, summary = support.open_camera_session(
        request,
        config=config,
        cv2_module=cv2_module,
    )
    return {
        "session": support.build_camera_session_payload(session_entry),
        "summary": support.build_value_payload(summary),
    }
