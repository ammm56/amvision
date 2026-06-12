"""OpenCV 基础节点包的 backend entrypoint。"""

from __future__ import annotations

from custom_nodes.opencv_basic_nodes.backend.nodes import NODE_HANDLERS
from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """把 OpenCV 基础节点 handler 注册到 workflow 运行时注册表。

    参数：
    - context：当前 node pack 的注册上下文。
    """

    for node_type_id, handler in NODE_HANDLERS:
        context.register_python_callable(node_type_id, handler)
