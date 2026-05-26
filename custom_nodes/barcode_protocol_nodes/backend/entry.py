"""Barcode/QR 协议节点包的 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.barcode_protocol_nodes.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 Barcode/QR 协议节点包中全部显式节点 handler。

    参数：
    - context：当前 node pack 的注册上下文。
    """

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(node_type_id, handler)

