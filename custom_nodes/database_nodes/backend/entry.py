"""Database 节点包统一 backend entrypoint。"""

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.database_nodes.providers.sql.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 SQL provider 节点。"""

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(
            node_type_id,
            handler,
            required_permission_scopes=(
                "integration.database.connect",
                "integration.database.write",
            ),
        )
