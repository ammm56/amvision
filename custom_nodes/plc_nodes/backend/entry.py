"""PLC 统一节点包 backend entrypoint。"""

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.plc_nodes.protocols.modbus_tcp.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册所有已实现 PLC 协议节点。"""

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(node_type_id, handler)
