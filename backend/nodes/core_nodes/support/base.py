"""core 节点目录扫描使用的共享规格定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.contracts.workflows.workflow_graph import (
    NODE_RUNTIME_PYTHON_CALLABLE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)


WorkflowNodeHandler = Callable[[WorkflowNodeExecutionRequest], dict[str, object]]


@dataclass(frozen=True)
class CoreNodeSpec:
    """描述单个 core 节点文件暴露的定义与可选 handler。

    字段：
    - node_definition：当前 core 节点的 NodeDefinition。
    - handler：当前 core 节点的可选运行时 handler；worker-task 节点可为空。
    """

    node_definition: NodeDefinition
    handler: WorkflowNodeHandler | None = None

    def register_handler(self, runtime_registry: WorkflowNodeRuntimeRegistry) -> None:
        """把当前节点的 handler 注册到 workflow 运行时注册表。

        参数：
        - runtime_registry：待写入 handler 的 workflow 节点运行时注册表。
        """

        if self.handler is None:
            return
        if self.node_definition.runtime_kind == NODE_RUNTIME_PYTHON_CALLABLE:
            runtime_registry.register_python_callable(self.node_definition, self.handler)
            return
        if self.node_definition.runtime_kind == NODE_RUNTIME_WORKER_TASK:
            runtime_registry.register_worker_task(self.node_definition, self.handler)
            return
        raise ServiceConfigurationError(
            "当前 core 节点运行方式不支持自动注册 handler",
            details={
                "node_type_id": self.node_definition.node_type_id,
                "runtime_kind": self.node_definition.runtime_kind,
            },
        )