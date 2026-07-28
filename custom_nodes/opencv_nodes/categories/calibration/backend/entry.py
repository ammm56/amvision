"""OpenCV 标定节点分类 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 OpenCV 标定节点处理函数。"""

    for node_type_id, handler in NODE_HANDLERS:
        context.register_python_callable(node_type_id, handler)
