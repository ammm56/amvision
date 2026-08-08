"""custom node 权限与执行策略装配测试。"""

from __future__ import annotations

import multiprocessing
from threading import Event
from time import sleep
from types import SimpleNamespace

import pytest

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CUSTOM,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
)
from backend.nodes.runtime_support import require_node_pack_permission
from backend.service.application.errors import (
    OperationTimeoutError,
    PermissionDeniedError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.contracts import WorkflowNodeExecutionRequest
from backend.service.application.workflows.execution.custom_node_policy import (
    CUSTOM_NODE_PROCESS_ISOLATED_METADATA_KEY,
    CUSTOM_NODE_TIMEOUT_EXIT_CODE,
    WorkflowCustomNodeRuntimePolicy,
)
from backend.service.application.workflows.execution.registry import WorkflowNodeRuntimeRegistry
from backend.service.application.workflows.worker.manager import (
    WorkflowRuntimeWorkerManager,
)
from backend.service.application.workflows.model_sessions import (
    WorkflowModelSessionManager,
)


def _custom_definition() -> NodeDefinition:
    """构造测试使用的 custom node 定义。"""

    return NodeDefinition(
        node_type_id="custom.test.policy-probe",
        display_name="Policy Probe",
        category="test.runtime.policy",
        implementation_kind=NODE_IMPLEMENTATION_CUSTOM,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        version="12.1.0",
        node_pack_id="test.nodes",
        node_pack_version="9.4.1",
    )


def _policy(**overrides: object) -> WorkflowCustomNodeRuntimePolicy:
    """构造测试使用的节点包执行策略。"""

    values: dict[str, object] = {
        "node_pack_id": "test.nodes",
        "node_pack_version": "9.4.1",
        "permission_scopes": frozenset({"objectstore.read.ref"}),
        "default_timeout_seconds": 15,
        "max_timeout_seconds": 30,
        "kill_grace_seconds": 2,
        "isolation": "workflow-process",
        "timeout_action": "terminate-workflow-process",
    }
    values.update(overrides)
    return WorkflowCustomNodeRuntimePolicy(**values)  # type: ignore[arg-type]


def test_registry_rejects_custom_handler_without_manifest_policy() -> None:
    """验证 custom handler 不能绕过 manifest 策略直接注册。"""

    registry = WorkflowNodeRuntimeRegistry()

    with pytest.raises(ServiceConfigurationError, match="缺少运行时执行策略"):
        registry.register_python_callable(_custom_definition(), lambda _request: {})


def test_registry_injects_manifest_permissions_timeout_and_isolation() -> None:
    """验证 handler 只接收注册表从 manifest 装配的可信策略。"""

    registry = WorkflowNodeRuntimeRegistry()
    definition = _custom_definition()
    observed: dict[str, object] = {}

    def handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        observed.update(
            {
                "node_pack_id": request.node_pack_id,
                "node_pack_version": request.node_pack_version,
                "permission_scopes": request.granted_permission_scopes,
                "timeout": request.node_timeout_seconds,
                "timeout_max": request.node_timeout_max_seconds,
                "isolation": request.process_isolation,
                "timeout_action": request.timeout_action,
            }
        )
        return {"ok": True}

    registry.register_python_callable(definition, handler, custom_node_policy=_policy())
    resolved_handler = registry.resolve_handler(node_definition=definition)

    result = resolved_handler(WorkflowNodeExecutionRequest(node_id="probe", node_definition=definition))

    assert result == {"ok": True}
    assert observed == {
        "node_pack_id": "test.nodes",
        "node_pack_version": "9.4.1",
        "permission_scopes": frozenset({"objectstore.read.ref"}),
        "timeout": 15,
        "timeout_max": 30,
        "isolation": "workflow-process",
        "timeout_action": "terminate-workflow-process",
    }


def test_platform_resource_permission_rejects_missing_scope() -> None:
    """验证 custom node 访问平台资源时缺少 scope 会被拒绝。"""

    definition = _custom_definition()
    request = WorkflowNodeExecutionRequest(
        node_id="probe",
        node_definition=definition,
        node_pack_id="test.nodes",
        node_pack_version="9.4.1",
        granted_permission_scopes=frozenset({"objectstore.read.ref"}),
    )

    with pytest.raises(PermissionDeniedError, match="未获得所需平台资源权限"):
        require_node_pack_permission(request, "objectstore.write.ref")


def test_platform_resource_permission_accepts_declared_scope() -> None:
    """验证声明并装配的 scope 可以访问对应平台资源。"""

    definition = _custom_definition()
    request = WorkflowNodeExecutionRequest(
        node_id="probe",
        node_definition=definition,
        node_pack_id="test.nodes",
        node_pack_version="9.4.1",
        granted_permission_scopes=frozenset({"objectstore.read.ref"}),
    )

    require_node_pack_permission(request, "objectstore.read.ref")


def test_registry_rejects_resource_entry_permission_missing_from_manifest() -> None:
    """验证 entrypoint 不能登记 manifest 未授予的真实资源入口。"""

    registry = WorkflowNodeRuntimeRegistry()
    definition = _custom_definition()

    with pytest.raises(
        ServiceConfigurationError,
        match="所需权限未在 manifest 中声明",
    ):
        registry.register_python_callable(
            definition,
            lambda _request: {},
            custom_node_policy=_policy(),
            required_permission_scopes=("integration.endpoint.invoke",),
        )


def test_registry_enforces_declared_resource_permission_before_handler() -> None:
    """验证已声明资源入口在 handler 调用前完成 scope 校验。"""

    registry = WorkflowNodeRuntimeRegistry()
    definition = _custom_definition()
    called = False

    def handler(_request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        nonlocal called
        called = True
        return {"ok": True}

    registry.register_python_callable(
        definition,
        handler,
        custom_node_policy=_policy(),
        required_permission_scopes=("objectstore.read.ref",),
    )

    result = registry.resolve_handler(node_definition=definition)(
        WorkflowNodeExecutionRequest(
            node_id="resource-probe",
            node_definition=definition,
        )
    )

    assert result == {"ok": True}
    assert called is True


def test_manifest_timeout_hard_exits_isolated_workflow_process() -> None:
    """验证阻塞 custom node 超时后以稳定退出码终止整个隔离进程。"""

    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_run_blocking_custom_node, daemon=False)

    process.start()
    process.join(timeout=8.0)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2.0)
        pytest.fail("custom node hard timeout 没有终止隔离进程")

    assert process.exitcode == CUSTOM_NODE_TIMEOUT_EXIT_CODE


def test_runtime_startup_maps_model_loader_hard_timeout_immediately() -> None:
    """验证模型预加载在 ready 前硬退出时立即返回 manifest timeout。"""

    manager = object.__new__(WorkflowRuntimeWorkerManager)
    handle = SimpleNamespace(
        started_event=Event(),
        process=SimpleNamespace(
            is_alive=lambda: False,
            exitcode=CUSTOM_NODE_TIMEOUT_EXIT_CODE,
        ),
        workflow_runtime_id="runtime-model-timeout",
    )

    with pytest.raises(OperationTimeoutError, match="model loader"):
        manager._wait_for_startup_state(handle, timeout_seconds=30.0)


def test_manifest_timeout_hard_exits_blocking_model_loader_process() -> None:
    """验证模型 provider 预加载也受 manifest hard timeout 约束。"""

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_run_blocking_custom_model_loader,
        daemon=False,
    )

    process.start()
    process.join(timeout=8.0)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2.0)
        pytest.fail("custom model loader hard timeout 没有终止隔离进程")

    assert process.exitcode == CUSTOM_NODE_TIMEOUT_EXIT_CODE


def _run_blocking_custom_node() -> None:
    """子进程入口：执行一个超过 manifest timeout 的 custom node。"""

    registry = WorkflowNodeRuntimeRegistry()
    definition = _custom_definition()

    def blocking_handler(_request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        sleep(30)
        return {}

    registry.register_python_callable(
        definition,
        blocking_handler,
        custom_node_policy=_policy(
            default_timeout_seconds=1,
            max_timeout_seconds=1,
            kill_grace_seconds=0,
        ),
    )
    handler = registry.resolve_handler(node_definition=definition)
    handler(
        WorkflowNodeExecutionRequest(
            node_id="blocking",
            node_definition=definition,
            execution_metadata={CUSTOM_NODE_PROCESS_ISOLATED_METADATA_KEY: True},
        )
    )


def _run_blocking_custom_model_loader() -> None:
    """子进程入口：执行超过 manifest timeout 的模型 provider。"""

    class _BlockingProvider:
        model_family = "blocking"

        def load(self, **_kwargs: object) -> object:
            sleep(30)
            raise AssertionError("blocking provider 不应返回")

        def warmup(self, **_kwargs: object) -> object:
            return {}

        def validate(self, **_kwargs: object) -> dict[str, object]:
            return {}

        def close(self, _session: object) -> None:
            return None

    registry = WorkflowNodeRuntimeRegistry()
    loader_definition = NodeDefinition(
        node_type_id="custom.test.load-checkpoint",
        display_name="Blocking Load Checkpoint",
        category="test.runtime.policy",
        implementation_kind=NODE_IMPLEMENTATION_CUSTOM,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        version="1.0.0",
        node_pack_id="test.nodes",
        node_pack_version="9.4.1",
    )
    registry.register_node_definition(loader_definition)
    registry.register_model_session_provider(
        loader_definition.node_type_id,
        _BlockingProvider(),  # type: ignore[arg-type]
        custom_node_policy=_policy(
            permission_scopes=frozenset({"model.asset.read"}),
            default_timeout_seconds=1,
            max_timeout_seconds=1,
            kill_grace_seconds=0,
        ),
        required_permission_scopes=("model.asset.read",),
    )
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    manager.prepare_template(
        scope_id="runtime:blocking-model",
        template=WorkflowGraphTemplate(
            template_id="blocking-model",
            template_version="1.0.0",
            display_name="Blocking Model",
            nodes=(
                WorkflowGraphNode(
                    node_id="loader",
                    node_type_id=loader_definition.node_type_id,
                ),
                WorkflowGraphNode(
                    node_id="consumer",
                    node_type_id="custom.test.model-consumer",
                ),
            ),
            edges=(
                WorkflowGraphEdge(
                    edge_id="loader-consumer",
                    source_node_id="loader",
                    source_port="model",
                    target_node_id="consumer",
                    target_port="model",
                ),
            ),
        ),
        runtime_context=object(),
    )
