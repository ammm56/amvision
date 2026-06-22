"""workflow 节点运行时注册表。"""

from __future__ import annotations

from collections.abc import Callable

from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.execution.contracts import WorkflowNodeExecutionRequest


class WorkflowNodeRuntimeRegistry:
    """维护最小节点目录和运行时处理函数的注册表。"""

    def __init__(self) -> None:
        """初始化空的节点运行时注册表。"""

        self._node_definitions: dict[str, NodeDefinition] = {}
        self._python_callable_handlers: dict[str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]] = {}
        self._worker_task_handlers: dict[str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]] = {}

    def register_node_definition(self, node_definition: NodeDefinition) -> None:
        """只注册节点定义，不附带处理函数。"""

        self._node_definitions[node_definition.node_type_id] = node_definition

    def clear(self) -> None:
        """清空当前注册表中的节点定义与处理函数。"""

        self._node_definitions.clear()
        self._python_callable_handlers.clear()
        self._worker_task_handlers.clear()

    def register_python_callable(
        self,
        node_definition: NodeDefinition,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    ) -> None:
        """注册 python-callable 节点及其执行函数。"""

        if node_definition.runtime_kind != "python-callable":
            raise InvalidRequestError(
                "python-callable 注册的节点定义 runtime_kind 不匹配",
                details={"node_type_id": node_definition.node_type_id},
            )
        self.register_node_definition(node_definition)
        self._python_callable_handlers[node_definition.node_type_id] = handler

    def register_worker_task(
        self,
        node_definition: NodeDefinition,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    ) -> None:
        """注册 worker-task 节点及其执行函数。"""

        if node_definition.runtime_kind != "worker-task":
            raise InvalidRequestError(
                "worker-task 注册的节点定义 runtime_kind 不匹配",
                details={"node_type_id": node_definition.node_type_id},
            )
        self.register_node_definition(node_definition)
        self._worker_task_handlers[node_definition.node_type_id] = handler

    def list_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回当前注册表中的全部节点定义。"""

        return tuple(self._node_definitions.values())

    def get_node_definition(self, node_type_id: str) -> NodeDefinition:
        """按节点类型 id 返回节点定义。"""

        node_definition = self._node_definitions.get(node_type_id)
        if node_definition is None:
            raise ServiceConfigurationError(
                "当前节点注册表缺少所需 NodeDefinition",
                details={"node_type_id": node_type_id},
            )
        return node_definition

    def has_registered_handler(self, *, node_definition: NodeDefinition) -> bool:
        """判断当前节点定义是否已经完成对应 runtime handler 注册。"""

        if node_definition.runtime_kind == "python-callable":
            return node_definition.node_type_id in self._python_callable_handlers
        if node_definition.runtime_kind == "worker-task":
            return node_definition.node_type_id in self._worker_task_handlers
        return False

    def resolve_handler(
        self,
        *,
        node_definition: NodeDefinition,
    ) -> Callable[[WorkflowNodeExecutionRequest], dict[str, object]]:
        """根据节点定义的 runtime_kind 返回对应处理函数。"""

        if node_definition.runtime_kind == "python-callable":
            handler = self._python_callable_handlers.get(node_definition.node_type_id)
            if handler is None:
                raise ServiceConfigurationError(
                    "当前节点注册表缺少 python-callable 处理函数",
                    details={"node_type_id": node_definition.node_type_id},
                )
            return handler
        if node_definition.runtime_kind == "worker-task":
            handler = self._worker_task_handlers.get(node_definition.node_type_id)
            if handler is None:
                raise ServiceConfigurationError(
                    "当前节点注册表缺少 worker-task 处理函数",
                    details={"node_type_id": node_definition.node_type_id},
                )
            return handler
        raise ServiceConfigurationError(
            "当前最小图执行器仅支持 python-callable 和 worker-task 节点",
            details={
                "node_type_id": node_definition.node_type_id,
                "runtime_kind": node_definition.runtime_kind,
            },
        )
