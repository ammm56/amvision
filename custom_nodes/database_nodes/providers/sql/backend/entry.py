"""Database SQL节点包的 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.database_nodes.providers.sql.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册Database SQL节点包中的全部 python-callable 节点。"""

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(
            node_type_id,
            handler,
            required_permission_scopes=(
                "integration.database.connect",
                "integration.database.write",
            ),
        )
