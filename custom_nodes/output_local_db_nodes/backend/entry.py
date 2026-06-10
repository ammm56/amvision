"""本地数据库输出节点包的 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)
from custom_nodes.output_local_db_nodes.backend.nodes import NODE_HANDLERS


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册本地数据库输出节点包中的全部 python-callable 节点。"""

    for node_type_id, handler in NODE_HANDLERS.items():
        context.register_python_callable(node_type_id, handler)
