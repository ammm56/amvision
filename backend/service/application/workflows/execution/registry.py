"""workflow 节点运行时注册表。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from backend.contracts.workflows.workflow_graph import NODE_IMPLEMENTATION_CUSTOM, NodeDefinition
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.workflows.execution.contracts import WorkflowNodeExecutionRequest
from backend.service.application.workflows.execution.custom_node_policy import (
    CUSTOM_NODE_PROCESS_ISOLATED_METADATA_KEY,
    CustomNodeHardTimeoutGuard,
    WorkflowCustomNodeRuntimePolicy,
    require_custom_node_permission,
    validate_custom_node_required_permissions,
)

if TYPE_CHECKING:
    from backend.service.application.workflows.model_sessions import (
        WorkflowModelSessionProvider,
    )


class WorkflowNodeRuntimeRegistry:
    """维护最小节点目录和运行时处理函数的注册表。"""

    def __init__(self) -> None:
        """初始化空的节点运行时注册表。"""

        self._node_definitions: dict[str, NodeDefinition] = {}
        self._python_callable_handlers: dict[str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]] = {}
        self._worker_task_handlers: dict[str, Callable[[WorkflowNodeExecutionRequest], dict[str, object]]] = {}
        self._model_session_providers: dict[str, WorkflowModelSessionProvider] = {}
        self._custom_node_policies: dict[str, WorkflowCustomNodeRuntimePolicy] = {}
        self._custom_node_required_permissions: dict[str, tuple[str, ...]] = {}
        self._model_session_required_permissions: dict[str, tuple[str, ...]] = {}

    def register_node_definition(self, node_definition: NodeDefinition) -> None:
        """只注册节点定义，不附带处理函数。"""

        self._node_definitions[node_definition.node_type_id] = node_definition

    def clear(self) -> None:
        """清空当前注册表中的节点定义与处理函数。"""

        self._node_definitions.clear()
        self._python_callable_handlers.clear()
        self._worker_task_handlers.clear()
        self._model_session_providers.clear()
        self._custom_node_policies.clear()
        self._custom_node_required_permissions.clear()
        self._model_session_required_permissions.clear()

    def register_model_session_provider(
        self,
        loader_node_type_id: str,
        provider: WorkflowModelSessionProvider,
        *,
        custom_node_policy: WorkflowCustomNodeRuntimePolicy | None = None,
        required_permission_scopes: tuple[str, ...] = (),
    ) -> None:
        """为一个 Load Checkpoint 节点注册模型生命周期 provider。"""

        node_definition = self.get_node_definition(loader_node_type_id)
        self._register_custom_node_policy(node_definition, custom_node_policy)
        normalized_scopes = self._validate_required_permissions(
            node_definition=node_definition,
            custom_node_policy=custom_node_policy,
            required_permission_scopes=required_permission_scopes,
        )
        self._model_session_providers[loader_node_type_id] = provider
        self._model_session_required_permissions[loader_node_type_id] = (
            normalized_scopes
        )

    def get_model_session_provider(
        self, loader_node_type_id: str
    ) -> WorkflowModelSessionProvider | None:
        """读取 loader 节点对应的 provider；普通节点返回 None。"""

        return self._model_session_providers.get(loader_node_type_id)

    def require_model_session_provider_permissions(
        self,
        loader_node_type_id: str,
    ) -> None:
        """在模型资产加载前强制校验 provider 的 manifest 权限。"""

        node_definition = self.get_node_definition(loader_node_type_id)
        required_scopes = self._model_session_required_permissions.get(
            loader_node_type_id,
            (),
        )
        if not required_scopes:
            return
        policy = self._custom_node_policies.get(loader_node_type_id)
        if policy is None:
            raise ServiceConfigurationError(
                "custom model session provider 缺少运行时执行策略",
                details={"node_type_id": loader_node_type_id},
            )
        request = WorkflowNodeExecutionRequest(
            node_id=f"model-session:{loader_node_type_id}",
            node_definition=node_definition,
            node_pack_id=policy.node_pack_id,
            node_pack_version=policy.node_pack_version,
            granted_permission_scopes=policy.permission_scopes,
        )
        for permission_scope in required_scopes:
            require_custom_node_permission(request, permission_scope)

    def register_python_callable(
        self,
        node_definition: NodeDefinition,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
        *,
        custom_node_policy: WorkflowCustomNodeRuntimePolicy | None = None,
        required_permission_scopes: tuple[str, ...] = (),
    ) -> None:
        """注册 python-callable 节点及其执行函数。"""

        if node_definition.runtime_kind != "python-callable":
            raise InvalidRequestError(
                "python-callable 注册的节点定义 runtime_kind 不匹配",
                details={"node_type_id": node_definition.node_type_id},
            )
        self.register_node_definition(node_definition)
        self._python_callable_handlers[node_definition.node_type_id] = handler
        self._register_custom_node_policy(node_definition, custom_node_policy)
        self._custom_node_required_permissions[node_definition.node_type_id] = (
            self._validate_required_permissions(
                node_definition=node_definition,
                custom_node_policy=custom_node_policy,
                required_permission_scopes=required_permission_scopes,
            )
        )

    def register_worker_task(
        self,
        node_definition: NodeDefinition,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
        *,
        custom_node_policy: WorkflowCustomNodeRuntimePolicy | None = None,
        required_permission_scopes: tuple[str, ...] = (),
    ) -> None:
        """注册 worker-task 节点及其执行函数。"""

        if node_definition.runtime_kind != "worker-task":
            raise InvalidRequestError(
                "worker-task 注册的节点定义 runtime_kind 不匹配",
                details={"node_type_id": node_definition.node_type_id},
            )
        self.register_node_definition(node_definition)
        self._worker_task_handlers[node_definition.node_type_id] = handler
        self._register_custom_node_policy(node_definition, custom_node_policy)
        self._custom_node_required_permissions[node_definition.node_type_id] = (
            self._validate_required_permissions(
                node_definition=node_definition,
                custom_node_policy=custom_node_policy,
                required_permission_scopes=required_permission_scopes,
            )
        )

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
            return self._wrap_custom_node_handler(node_definition, handler)
        if node_definition.runtime_kind == "worker-task":
            handler = self._worker_task_handlers.get(node_definition.node_type_id)
            if handler is None:
                raise ServiceConfigurationError(
                    "当前节点注册表缺少 worker-task 处理函数",
                    details={"node_type_id": node_definition.node_type_id},
                )
            return self._wrap_custom_node_handler(node_definition, handler)
        raise ServiceConfigurationError(
            "当前最小图执行器仅支持 python-callable 和 worker-task 节点",
            details={
                "node_type_id": node_definition.node_type_id,
                "runtime_kind": node_definition.runtime_kind,
            },
        )

    def get_custom_node_policy(
        self,
        node_type_id: str,
    ) -> WorkflowCustomNodeRuntimePolicy | None:
        """读取 custom node 已登记的执行策略。"""

        return self._custom_node_policies.get(node_type_id)

    def _register_custom_node_policy(
        self,
        node_definition: NodeDefinition,
        policy: WorkflowCustomNodeRuntimePolicy | None,
    ) -> None:
        """为 custom node 强制登记来源、权限、超时和隔离规则。"""

        if node_definition.implementation_kind != NODE_IMPLEMENTATION_CUSTOM:
            if policy is not None:
                raise InvalidRequestError(
                    "core node 不能登记 custom node 执行策略",
                    details={"node_type_id": node_definition.node_type_id},
                )
            return
        if policy is None:
            raise ServiceConfigurationError(
                "custom node 缺少运行时执行策略",
                details={"node_type_id": node_definition.node_type_id},
            )
        if (
            node_definition.node_pack_id != policy.node_pack_id
            or node_definition.node_pack_version != policy.node_pack_version
        ):
            raise ServiceConfigurationError(
                "custom node 执行策略与节点包身份不一致",
                details={
                    "node_type_id": node_definition.node_type_id,
                    "node_pack_id": node_definition.node_pack_id,
                    "node_pack_version": node_definition.node_pack_version,
                    "policy_node_pack_id": policy.node_pack_id,
                    "policy_node_pack_version": policy.node_pack_version,
                },
            )
        self._custom_node_policies[node_definition.node_type_id] = policy

    @staticmethod
    def _validate_required_permissions(
        *,
        node_definition: NodeDefinition,
        custom_node_policy: WorkflowCustomNodeRuntimePolicy | None,
        required_permission_scopes: tuple[str, ...],
    ) -> tuple[str, ...]:
        """校验 handler/provider 声明的真实平台资源入口。"""

        if not required_permission_scopes:
            return ()
        if node_definition.implementation_kind != NODE_IMPLEMENTATION_CUSTOM:
            raise InvalidRequestError(
                "core node 不能声明 node pack permission scope",
                details={"node_type_id": node_definition.node_type_id},
            )
        if custom_node_policy is None:
            raise ServiceConfigurationError(
                "custom node 资源入口缺少运行时执行策略",
                details={"node_type_id": node_definition.node_type_id},
            )
        return validate_custom_node_required_permissions(
            node_type_id=node_definition.node_type_id,
            policy=custom_node_policy,
            required_permission_scopes=required_permission_scopes,
        )

    def _wrap_custom_node_handler(
        self,
        node_definition: NodeDefinition,
        handler: Callable[[WorkflowNodeExecutionRequest], dict[str, object]],
    ) -> Callable[[WorkflowNodeExecutionRequest], dict[str, object]]:
        """把 manifest 策略注入 custom node 请求，core node 保持原处理函数。"""

        if node_definition.implementation_kind != NODE_IMPLEMENTATION_CUSTOM:
            return handler
        policy = self._custom_node_policies.get(node_definition.node_type_id)
        if policy is None:
            raise ServiceConfigurationError(
                "custom node 缺少运行时执行策略",
                details={"node_type_id": node_definition.node_type_id},
            )

        def invoke(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
            hard_timeout_guard = (
                CustomNodeHardTimeoutGuard(
                    node_id=request.node_id,
                    node_type_id=node_definition.node_type_id,
                    timeout_seconds=policy.default_timeout_seconds,
                    kill_grace_seconds=policy.kill_grace_seconds,
                )
                if request.execution_metadata.get(CUSTOM_NODE_PROCESS_ISOLATED_METADATA_KEY)
                is True
                else None
            )
            guarded_request = replace(
                request,
                node_pack_id=policy.node_pack_id,
                node_pack_version=policy.node_pack_version,
                granted_permission_scopes=policy.permission_scopes,
                node_timeout_seconds=policy.default_timeout_seconds,
                node_timeout_max_seconds=policy.max_timeout_seconds,
                process_isolation=policy.isolation,
                timeout_action=policy.timeout_action,
                node_cancellation_event=(
                    hard_timeout_guard.cancellation_event
                    if hard_timeout_guard is not None
                    else None
                ),
            )
            for permission_scope in self._custom_node_required_permissions.get(
                node_definition.node_type_id,
                (),
            ):
                require_custom_node_permission(
                    guarded_request,
                    permission_scope,
                )
            if hard_timeout_guard is None:
                return dict(handler(guarded_request))
            return hard_timeout_guard.run(lambda: dict(handler(guarded_request)))

        return invoke
