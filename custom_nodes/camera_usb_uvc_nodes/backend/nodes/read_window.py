"""USB / UVC 相机会话窗口读帧节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime import capture, config, payloads, sessions, streaming
from custom_nodes.camera_usb_uvc_nodes.specs import READ_WINDOW_NODE_TYPE_ID


NODE_TYPE_ID = READ_WINDOW_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """从当前 USB / UVC 采流缓冲中读取 frame-window.v1。"""

    cv2_module, _ = capture.require_opencv_imports()
    _session_payload, session_entry = sessions.require_camera_session_entry(request)
    window_config = config.resolve_read_window_config(request)
    frame_window_payload, summary = streaming.read_camera_session_window(
        request,
        entry=session_entry,
        config=window_config,
        cv2_module=cv2_module,
    )
    return {
        "session": payloads.build_camera_session_payload(session_entry),
        "frames": frame_window_payload,
        "summary": payloads.build_value_payload(summary),
    }
