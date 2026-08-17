"""workflow 节点运行时注册表。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.nodes.concurrency_policy import apply_inferred_concurrency_policy
from backend.nodes.definition_metadata import enrich_node_definition_metadata

if TYPE_CHECKING:
    from backend.service.application.workflows.model_sessions import (
        WorkflowModelSessionProvider,
    )


class WorkflowNodeRuntimeRegistry:
    """维护最小节点目录和运行时处理函数的注册表。"""

    def __init__(self) -> None:
        """初始化空的节点运行时注册表。"""

        self._node_definitions: dict[str, NodeDefinition] = {}
        self._python_callable_handlers: dict[
            str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]
        ] = {}
        self._worker_task_handlers: dict[
            str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]
        ] = {}
        self._model_session_providers: dict[str, WorkflowModelSessionProvider] = {}

    def register_node_definition(self, node_definition: NodeDefinition) -> None:
        """幂等注册节点定义，并拒绝同 id 的冲突定义。"""

        node_definition = apply_inferred_concurrency_policy(node_definition)
        node_definition = enrich_node_definition_metadata(node_definition)
        existing_definition = self._node_definitions.get(node_definition.node_type_id)
        if existing_definition is None:
            self._node_definitions[node_definition.node_type_id] = node_definition
            return
        if existing_definition.model_dump(mode="json") != node_definition.model_dump(
            mode="json"
        ):
            raise ServiceConfigurationError(
                "节点运行时注册表存在冲突定义",
                details={"node_type_id": node_definition.node_type_id},
            )

    def clear(self) -> None:
        """清空当前注册表中的节点定义与处理函数。"""

        self._node_definitions.clear()
        self._python_callable_handlers.clear()
        self._worker_task_handlers.clear()
        self._model_session_providers.clear()

    def register_model_session_provider(
        self,
        loader_node_type_id: str,
        provider: WorkflowModelSessionProvider,
    ) -> None:
        """为一个 Load Checkpoint 节点注册模型生命周期 provider。"""

        self.get_node_definition(loader_node_type_id)
        existing_provider = self._model_session_providers.get(loader_node_type_id)
        if existing_provider is not None and existing_provider is not provider:
            raise ServiceConfigurationError(
                "模型 session provider 重复注册",
                details={"node_type_id": loader_node_type_id},
            )
        self._model_session_providers[loader_node_type_id] = provider

    def get_model_session_provider(
        self, loader_node_type_id: str
    ) -> WorkflowModelSessionProvider | None:
        """读取 loader 节点对应的 provider；普通节点返回 None。"""

        return self._model_session_providers.get(loader_node_type_id)

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
        existing_handler = self._python_callable_handlers.get(
            node_definition.node_type_id
        )
        if existing_handler is not None and existing_handler is not handler:
            raise ServiceConfigurationError(
                "python-callable 节点处理函数重复注册",
                details={"node_type_id": node_definition.node_type_id},
            )
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
        existing_handler = self._worker_task_handlers.get(node_definition.node_type_id)
        if existing_handler is not None and existing_handler is not handler:
            raise ServiceConfigurationError(
                "worker-task 节点处理函数重复注册",
                details={"node_type_id": node_definition.node_type_id},
            )
        self._worker_task_handlers[node_definition.node_type_id] = handler

    def replace_python_callable_handler(
        self,
        node_type_id: str,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    ) -> None:
        """显式替换已注册 python-callable 节点的处理函数。"""

        node_definition = self.get_node_definition(node_type_id)
        if node_definition.runtime_kind != "python-callable":
            raise InvalidRequestError(
                "替换处理函数的节点不是 python-callable",
                details={"node_type_id": node_type_id},
            )
        if node_type_id not in self._python_callable_handlers:
            raise ServiceConfigurationError(
                "当前节点注册表缺少可替换的 python-callable 处理函数",
                details={"node_type_id": node_type_id},
            )
        self._python_callable_handlers[node_type_id] = handler

    def replace_worker_task_handler(
        self,
        node_type_id: str,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    ) -> None:
        """显式替换已注册 worker-task 节点的处理函数。"""

        node_definition = self.get_node_definition(node_type_id)
        if node_definition.runtime_kind != "worker-task":
            raise InvalidRequestError(
                "替换处理函数的节点不是 worker-task",
                details={"node_type_id": node_type_id},
            )
        if node_type_id not in self._worker_task_handlers:
            raise ServiceConfigurationError(
                "当前节点注册表缺少可替换的 worker-task 处理函数",
                details={"node_type_id": node_type_id},
            )
        self._worker_task_handlers[node_type_id] = handler

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
