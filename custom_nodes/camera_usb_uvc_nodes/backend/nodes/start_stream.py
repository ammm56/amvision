"""USB / UVC 相机会话启动采流节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime import config, payloads, sessions, streaming
from custom_nodes.camera_usb_uvc_nodes.specs import START_STREAM_NODE_TYPE_ID


NODE_TYPE_ID = START_STREAM_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """为当前 USB / UVC 相机会话启动后台采流线程。"""

    _session_payload, session_entry = sessions.require_camera_session_entry(request)
    stream_config = config.resolve_start_stream_config(request)
    summary = streaming.start_camera_session_stream(
        session_entry,
        config=stream_config,
    )
    return {
        "session": payloads.build_camera_session_payload(session_entry),
        "summary": payloads.build_value_payload(summary),
    }
