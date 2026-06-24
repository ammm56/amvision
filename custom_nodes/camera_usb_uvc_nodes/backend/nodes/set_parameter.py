"""USB / UVC 相机会话参数写入节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend.runtime import capture, config, parameters, payloads, sessions
from custom_nodes.camera_usb_uvc_nodes.specs import SET_PARAMETER_NODE_TYPE_ID


NODE_TYPE_ID = SET_PARAMETER_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """写入当前相机会话的一组参数值。"""

    cv2_module, _ = capture.require_opencv_imports()
    _session_payload, session_entry = sessions.require_camera_session_entry(request)
    set_config = config.resolve_set_parameters_config(request)
    requested_values, observed_values = parameters.set_camera_session_parameter_values(
        session_entry,
        parameter_values=set_config.parameter_values,
        verify_after_set=set_config.verify_after_set,
        cv2_module=cv2_module,
    )
    return {
        "session": payloads.build_camera_session_payload(session_entry),
        "result": payloads.build_value_payload(
            {
                **payloads.build_camera_session_summary(
                    session_entry,
                    operation="set_parameter",
                ),
                "verify_after_set": set_config.verify_after_set,
                "requested_values": requested_values,
                "observed_values": observed_values,
            }
        ),
    }
