"""OpenCV 匹配节点包的 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.opencv_matching_nodes.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """把 OpenCV 匹配节点 handler 注册到 workflow 运行时注册表。"""

    for node_type_id, handler in NODE_HANDLERS:
        context.register_python_callable(node_type_id, handler)
