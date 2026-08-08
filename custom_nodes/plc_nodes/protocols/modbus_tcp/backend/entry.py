"""PLC Modbus TCP 节点包的 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.plc_nodes.protocols.modbus_tcp.backend.nodes import NODE_HANDLERS
from custom_nodes.plc_nodes.protocols.modbus_tcp.specs import (
    READ_VALUE_NODE_TYPE_ID,
    WAIT_CONDITION_NODE_TYPE_ID,
    WRITE_RESULT_SIGNALS_NODE_TYPE_ID,
    WRITE_VALUE_NODE_TYPE_ID,
)


_REQUIRED_PERMISSION_SCOPES_BY_NODE_TYPE_ID = {
    READ_VALUE_NODE_TYPE_ID: ("integration.plc.modbus.read",),
    WAIT_CONDITION_NODE_TYPE_ID: ("integration.plc.modbus.read",),
    WRITE_VALUE_NODE_TYPE_ID: ("integration.plc.modbus.write",),
    WRITE_RESULT_SIGNALS_NODE_TYPE_ID: ("integration.plc.modbus.write",),
}


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 PLC Modbus TCP 节点包中的全部 python-callable 节点。"""

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(
            node_type_id,
            handler,
            required_permission_scopes=(
                _REQUIRED_PERMISSION_SCOPES_BY_NODE_TYPE_ID[node_type_id]
            ),
        )
