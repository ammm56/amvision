"""USB / UVC 相机节点包 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.camera_usb_uvc_nodes.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """把 USB / UVC 相机节点 handler 注册到 workflow 运行时注册表。"""

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(node_type_id, handler)

