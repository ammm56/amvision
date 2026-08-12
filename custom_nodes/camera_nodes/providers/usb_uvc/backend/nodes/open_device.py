"""USB / UVC 相机打开节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_nodes.providers.usb_uvc.backend.runtime import capture, config, payloads, sessions
from custom_nodes.camera_nodes.providers.usb_uvc.backend.runtime.resource_scope import (
    register_camera_session_resource,
)
from custom_nodes.camera_nodes.providers.usb_uvc.specs import OPEN_DEVICE_NODE_TYPE_ID


NODE_TYPE_ID = OPEN_DEVICE_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """打开一个可跨节点复用的 USB / UVC 相机会话。"""

    cv2_module, _ = capture.require_opencv_imports()
    open_config = config.resolve_open_config(request, cv2_module=cv2_module)
    session_entry, summary = sessions.open_camera_session(
        request,
        config=open_config,
        cv2_module=cv2_module,
    )
    session_payload = payloads.build_camera_session_payload(session_entry)
    register_camera_session_resource(
        request,
        session_entry=session_entry,
        session_payload=session_payload,
        closer=sessions.close_camera_session,
    )
    return {
        "session": session_payload,
        "summary": payloads.build_value_payload(summary),
    }
