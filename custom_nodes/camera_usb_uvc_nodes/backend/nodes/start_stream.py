"""USB / UVC 相机会话启动采流节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend import support
from custom_nodes.camera_usb_uvc_nodes.specs import START_STREAM_NODE_TYPE_ID


NODE_TYPE_ID = START_STREAM_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """为当前 USB / UVC 相机会话启动后台采流线程。"""

    _session_payload, session_entry = support.require_camera_session_entry(request)
    config = support.resolve_start_stream_config(request)
    summary = support.start_camera_session_stream(
        session_entry,
        config=config,
    )
    return {
        "session": support.build_camera_session_payload(session_entry),
        "summary": support.build_value_payload(summary),
    }
