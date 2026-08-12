"""USB / UVC Camera 会话与 Workflow ResourceScope 的绑定。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


_CAMERA_SESSION_RESOURCE_KIND = "camera.usb-uvc.session"


def register_camera_session_resource(
    request: WorkflowNodeExecutionRequest,
    *,
    session_entry: object,
    session_payload: dict[str, object],
    closer: Callable[[WorkflowNodeExecutionRequest], object],
) -> None:
    """登记相机会话，确保 Workflow 结束时执行关闭。"""

    scope = get_or_create_workflow_resource_scope(request.execution_metadata)
    cleanup_request = replace(
        request,
        input_values={**request.input_values, "session": dict(session_payload)},
    )
    scope.register(
        (_CAMERA_SESSION_RESOURCE_KIND, id(session_entry)),
        cleanup_request,
        lambda resource: closer(resource),
    )


def unregister_camera_session_resource(
    request: WorkflowNodeExecutionRequest,
    *,
    session_entry: object,
) -> None:
    """显式关闭成功后解除 Workflow 兜底关闭登记。"""

    scope = get_or_create_workflow_resource_scope(request.execution_metadata)
    scope.unregister((_CAMERA_SESSION_RESOURCE_KIND, id(session_entry)))


__all__ = [
    "register_camera_session_resource",
    "unregister_camera_session_resource",
]
