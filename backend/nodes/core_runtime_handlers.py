"""core workflow 节点默认 handler 注册。"""

from __future__ import annotations

from backend.nodes.core_nodes import get_core_node_specs
from backend.service.application.workflows.graph_executor import WorkflowNodeRuntimeRegistry


def register_core_node_handlers(runtime_registry: WorkflowNodeRuntimeRegistry) -> None:
    """为当前 runtime registry 注册内建 core 节点 handler。

    参数：
    - runtime_registry：待写入 handler 的节点运行时注册表。
    """

    for core_node_spec in get_core_node_specs():
        core_node_spec.register_handler(runtime_registry)