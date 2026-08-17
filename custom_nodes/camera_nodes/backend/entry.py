"""Camera 节点包统一 backend entrypoint。"""

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.camera_nodes.providers.usb_uvc.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册当前已实现的 Camera provider 节点。"""

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(node_type_id, handler)
