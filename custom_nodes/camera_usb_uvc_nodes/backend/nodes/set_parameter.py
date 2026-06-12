"""USB / UVC 相机会话参数写入节点。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.camera_usb_uvc_nodes.backend import support
from custom_nodes.camera_usb_uvc_nodes.specs import SET_PARAMETER_NODE_TYPE_ID


NODE_TYPE_ID = SET_PARAMETER_NODE_TYPE_ID


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """写入当前相机会话的一组参数值。"""

    cv2_module, _ = support.require_opencv_imports()
    _session_payload, session_entry = support.require_camera_session_entry(request)
    config = support.resolve_set_parameters_config(request)
    requested_values, observed_values = support.set_camera_session_parameter_values(
        session_entry,
        parameter_values=config.parameter_values,
        verify_after_set=config.verify_after_set,
        cv2_module=cv2_module,
    )
    return {
        "session": support.build_camera_session_payload(session_entry),
        "result": support.build_value_payload(
            {
                **support.build_camera_session_summary(
                    session_entry,
                    operation="set_parameter",
                ),
                "verify_after_set": config.verify_after_set,
                "requested_values": requested_values,
                "observed_values": observed_values,
            }
        ),
    }
