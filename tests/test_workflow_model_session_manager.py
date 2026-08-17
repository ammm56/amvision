"""Workflow Model Session 生命周期测试。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Barrier, Event, Lock, Thread
from time import sleep

import pytest

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.execution.registry import (
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.workflows.model_sessions import (
    WORKFLOW_PREVIEW_MODEL_SESSION_SCOPE_PREFIX,
    WorkflowModelSessionLoadResult,
    WorkflowModelSessionManager,
    build_workflow_preview_model_session_scope_id,
)
from backend.service.application.errors import ResourceInUseError


@dataclass
class _FakeSession:
    closed: bool = False


class _FakeProvider:
    model_family = "fake"

    def __init__(self) -> None:
        self.events: list[str] = []

    def load(self, **_):
        self.events.append("load")
        return WorkflowModelSessionLoadResult(
            session=_FakeSession(),
            model_family="fake",
            model_asset_id="fake/default",
            checkpoint_sha256="abc",
            resolved_device="cpu",
            resolved_precision="fp32",
            capabilities=("infer",),
        )

    def warmup(self, **_):
        self.events.append("warmup")
        return {"ok": True}

    def validate(self, **_):
        self.events.append("validate")
        return {"warmup": "passed"}

    def close(self, session):
        self.events.append("close")
        session.closed = True


def test_prepare_template_is_serial_and_idempotent() -> None:
    """验证 provider 生命周期顺序和同一 scope 的幂等复用。"""

    registry, provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    template = _build_template()

    first = manager.prepare_template(
        scope_id="runtime:one", template=template, runtime_context=object()
    )
    second = manager.prepare_template(
        scope_id="runtime:one", template=template, runtime_context=object()
    )

    assert provider.events == ["load", "warmup", "validate"]
    assert first == second
    assert first[0].generation == 1
    assert manager.build_health_summary(scope_id="runtime:one")[
        "ready_session_count"
    ] == 1


def test_different_loaders_prepare_in_parallel_and_publish_atomically() -> None:
    """验证不同 loader 使用独立线程准备，并在全部成功后统一可见。"""

    registry = WorkflowNodeRuntimeRegistry()
    _register_fake_definition(registry)
    barrier = Barrier(2)
    event_lock = Lock()

    class _ParallelProvider(_FakeProvider):
        def load(self, **kwargs):
            loader_node = kwargs["loader_node"]
            with event_lock:
                self.events.append(f"load:{loader_node.node_id}")
            barrier.wait(timeout=1)
            return WorkflowModelSessionLoadResult(
                session=_FakeSession(),
                model_family="fake",
                model_asset_id=str(loader_node.parameters["model_asset_id"]),
                checkpoint_sha256="abc",
                resolved_device="cpu",
                resolved_precision="fp32",
                capabilities=("infer",),
            )

    provider = _ParallelProvider()
    _register_fake_provider(registry, provider)
    manager = WorkflowModelSessionManager(
        runtime_registry=registry,
        max_parallel_loads=2,
    )

    references = manager.prepare_template(
        scope_id="runtime:parallel",
        template=_build_two_loader_template(),
        runtime_context=object(),
    )

    assert [item.loader_node_id for item in references] == [
        "loader-a",
        "loader-b",
    ]
    health = manager.build_health_summary(scope_id="runtime:parallel")
    assert health["ready_session_count"] == 2
    assert health["startup_parallelism"] == 2


def test_parallel_prepare_failure_closes_every_new_session() -> None:
    """验证任一 loader 启动失败时不会留下半发布或未释放的 session。"""

    registry = WorkflowNodeRuntimeRegistry()
    _register_fake_definition(registry)
    barrier = Barrier(2)

    class _FailingProvider(_FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.sessions: list[_FakeSession] = []

        def load(self, **kwargs):
            loader_node = kwargs["loader_node"]
            session = _FakeSession()
            self.sessions.append(session)
            barrier.wait(timeout=1)
            return WorkflowModelSessionLoadResult(
                session=session,
                model_family="fake",
                model_asset_id=str(loader_node.parameters["model_asset_id"]),
                checkpoint_sha256="abc",
                resolved_device="cpu",
                resolved_precision="fp32",
                capabilities=("infer",),
                metadata={"loader_node_id": loader_node.node_id},
            )

        def validate(self, **kwargs):
            loader_node_id = kwargs["load_result"].metadata["loader_node_id"]
            if loader_node_id == "loader-b":
                raise RuntimeError("loader-b failed")
            return {"warmup": "passed"}

    provider = _FailingProvider()
    _register_fake_provider(registry, provider)
    manager = WorkflowModelSessionManager(
        runtime_registry=registry,
        max_parallel_loads=2,
    )

    with pytest.raises(RuntimeError, match="loader-b failed"):
        manager.prepare_template(
            scope_id="runtime:parallel-failure",
            template=_build_two_loader_template(),
            runtime_context=object(),
        )

    assert provider.sessions
    assert all(session.closed for session in provider.sessions)
    assert manager.build_health_summary(
        scope_id="runtime:parallel-failure"
    )["ready_session_count"] == 0


def test_close_scope_attempts_every_lease_when_one_provider_close_fails() -> None:
    """验证单个 Provider 释放失败不会让同 scope 的其他模型泄漏。"""

    registry = WorkflowNodeRuntimeRegistry()
    _register_fake_definition(registry)

    class _CloseFailingProvider(_FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.sessions: list[_FakeSession] = []
            self.close_count = 0

        def load(self, **kwargs):
            loader_node = kwargs["loader_node"]
            session = _FakeSession()
            self.sessions.append(session)
            return WorkflowModelSessionLoadResult(
                session=session,
                model_family="fake",
                model_asset_id=str(loader_node.parameters["model_asset_id"]),
                checkpoint_sha256="abc",
                resolved_device="cpu",
                resolved_precision="fp32",
                capabilities=("infer",),
            )

        def close(self, session):
            self.close_count += 1
            session.closed = True
            if self.close_count == 1:
                raise RuntimeError("first close failed")

    provider = _CloseFailingProvider()
    _register_fake_provider(registry, provider)
    manager = WorkflowModelSessionManager(
        runtime_registry=registry,
        max_parallel_loads=1,
    )
    manager.prepare_template(
        scope_id="runtime:close-failure",
        template=_build_two_loader_template(),
        runtime_context=object(),
    )

    with pytest.raises(RuntimeError, match="first close failed"):
        manager.close_scope("runtime:close-failure")

    assert provider.close_count == 2
    assert all(session.closed for session in provider.sessions)
    assert manager.build_health_summary(
        scope_id="runtime:close-failure"
    )["ready_session_count"] == 0


def test_scope_isolation_and_close_are_explicit() -> None:
    """验证不同 AppRuntime 不共享模型，并且关闭 scope 会释放对象。"""

    registry, provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    template = _build_template()
    manager.prepare_template(
        scope_id="runtime:one", template=template, runtime_context=object()
    )
    manager.prepare_template(
        scope_id="runtime:two", template=template, runtime_context=object()
    )

    assert provider.events.count("load") == 2
    manager.close_scope("runtime:one")
    assert provider.events.count("close") == 1
    assert manager.build_health_summary(scope_id="runtime:one")[
        "ready_session_count"
    ] == 0
    assert manager.build_health_summary(scope_id="runtime:two")[
        "ready_session_count"
    ] == 1


def test_lease_serializes_calls_for_one_model_session() -> None:
    """验证同一 loader 的下游分支不能并发使用模型对象。"""

    registry, _provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    template = _build_template()
    manager.prepare_template(
        scope_id="runtime:one", template=template, runtime_context=object()
    )
    payload = manager.build_reference_payload(
        scope_id="runtime:one", loader_node_id="loader"
    )
    lease = manager.resolve_reference(
        payload, expected_model_family="fake", capability="infer"
    )
    first_entered = Event()
    second_entered = Event()

    def first_call() -> None:
        with lease.locked_session(capability="infer"):
            first_entered.set()
            sleep(0.05)

    def second_call() -> None:
        first_entered.wait(timeout=1)
        with lease.locked_session(capability="infer"):
            second_entered.set()

    first_thread = Thread(target=first_call)
    second_thread = Thread(target=second_call)
    first_thread.start()
    second_thread.start()
    sleep(0.01)
    assert second_entered.is_set() is False
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)
    assert second_entered.is_set() is True


def test_stable_preview_scope_reuses_session_and_configuration_change_reloads() -> None:
    """验证 snapshot 路径变化不影响复用，只有 loader 配置变化才换代。"""

    registry, provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    scope_id = build_workflow_preview_model_session_scope_id(
        project_id="project-1",
        application_id="app-1",
    )

    first = manager.prepare_template(
        scope_id=scope_id,
        template=_build_template(model_asset_id="fake/a"),
        runtime_context=object(),
    )
    second = manager.prepare_template(
        scope_id=scope_id,
        template=_build_template(model_asset_id="fake/a"),
        runtime_context=object(),
    )
    third = manager.prepare_template(
        scope_id=scope_id,
        template=_build_template(model_asset_id="fake/b"),
        runtime_context=object(),
    )

    assert first == second
    assert third[0].generation == 2
    assert provider.events == [
        "load",
        "warmup",
        "validate",
        "close",
        "load",
        "warmup",
        "validate",
    ]


def test_node_scope_without_loader_keeps_existing_application_lease() -> None:
    """验证节点级执行裁剪不回收同应用完整图中仍存在的 loader。"""

    registry, provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    scope_id = "preview:project-1:app-1"
    template = _build_template()

    first = manager.prepare_template(
        scope_id=scope_id,
        template=template,
        runtime_context=object(),
    )
    node_scope = manager.prepare_template(
        scope_id=scope_id,
        template=template,
        runtime_context=object(),
        active_loader_node_ids=set(),
    )
    third = manager.prepare_template(
        scope_id=scope_id,
        template=template,
        runtime_context=object(),
        active_loader_node_ids={"loader"},
    )

    assert node_scope == ()
    assert third == first
    assert provider.events == ["load", "warmup", "validate"]
    assert manager.build_health_summary(scope_id=scope_id)[
        "ready_session_count"
    ] == 1


def test_non_loader_parameter_change_keeps_existing_application_lease() -> None:
    """验证普通节点参数变化不会使稳定 Preview scope 中的模型换代。"""

    registry, provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    scope_id = "preview:project-1:app-1"
    original_template = _build_template()
    changed_template = original_template.model_copy(
        update={
            "nodes": (
                original_template.nodes[0],
                original_template.nodes[1].model_copy(
                    update={"parameters": {"threshold": 0.75}}
                ),
            )
        }
    )

    first = manager.prepare_template(
        scope_id=scope_id,
        template=original_template,
        runtime_context=object(),
    )
    second = manager.prepare_template(
        scope_id=scope_id,
        template=changed_template,
        runtime_context=object(),
    )

    assert second == first
    assert provider.events == ["load", "warmup", "validate"]


def test_deleted_or_disabled_loader_closes_orphan_lease() -> None:
    """验证编辑图删除 Load Checkpoint 后不会遗留模型。"""

    registry, provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    manager.prepare_template(
        scope_id="preview:project-1:app-1",
        template=_build_template(),
        runtime_context=object(),
    )
    template_without_loader = WorkflowGraphTemplate(
        template_id="template-model-session",
        template_version="1.0.0",
        display_name="Model Session",
        nodes=(
            WorkflowGraphNode(
                node_id="consumer",
                node_type_id="custom.fake.infer",
            ),
        ),
    )

    prepared = manager.prepare_template(
        scope_id="preview:project-1:app-1",
        template=template_without_loader,
        runtime_context=object(),
    )

    assert prepared == ()
    assert provider.events.count("close") == 1
    assert manager.build_health_summary(
        scope_id="preview:project-1:app-1"
    )["ready_session_count"] == 0


def test_preview_scope_limit_evicts_previous_application() -> None:
    """验证 API 进程只保留配置允许数量的编辑态模型 scope。"""

    registry, provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    manager.prepare_template(
        scope_id="preview:project-1:app-1",
        template=_build_template(),
        runtime_context=object(),
    )

    evicted = manager.enforce_scope_limit(
        scope_prefix=WORKFLOW_PREVIEW_MODEL_SESSION_SCOPE_PREFIX,
        current_scope_id="preview:project-1:app-2",
        max_scope_count=1,
    )

    assert evicted == ("preview:project-1:app-1",)
    assert provider.events.count("close") == 1
    assert manager.build_health_summary(
        scope_id="preview:project-1:app-1"
    )["ready_session_count"] == 0


def test_preview_scope_rejects_duplicate_execution_without_queueing() -> None:
    """验证同应用重复 Preview 会立即失败，不在模型锁后排队。"""

    registry, _provider = _build_registry()
    manager = WorkflowModelSessionManager(runtime_registry=registry)
    first_entered = Event()
    release_first = Event()

    def hold_scope() -> None:
        with manager.locked_scope("preview:project-1:app-1"):
            first_entered.set()
            release_first.wait(timeout=1)

    thread = Thread(target=hold_scope)
    thread.start()
    assert first_entered.wait(timeout=1) is True
    try:
        with pytest.raises(ResourceInUseError):
            with manager.locked_scope(
                "preview:project-1:app-1",
                wait=False,
            ):
                pass
    finally:
        release_first.set()
        thread.join(timeout=1)


def _build_registry() -> tuple[WorkflowNodeRuntimeRegistry, _FakeProvider]:
    registry = WorkflowNodeRuntimeRegistry()
    _register_fake_definition(registry)
    provider = _FakeProvider()
    _register_fake_provider(registry, provider)
    return registry, provider


def _register_fake_provider(
    registry: WorkflowNodeRuntimeRegistry,
    provider: object,
) -> None:
    """按正式 custom node 契约注册测试模型 provider。"""

    registry.register_model_session_provider(
        "custom.fake.load-checkpoint",
        provider,  # type: ignore[arg-type]
    )


def _register_fake_definition(registry: WorkflowNodeRuntimeRegistry) -> None:
    """注册测试使用的通用 loader 定义。"""

    registry.register_node_definition(
        NodeDefinition(
            node_type_id="custom.fake.load-checkpoint",
            display_name="Fake Load Checkpoint",
            category="fake.model.loader",
            implementation_kind="custom-node",
            runtime_kind="python-callable",
            input_ports=(),
            output_ports=(),
            parameter_schema={"type": "object"},
            node_pack_id="fake.nodes",
            node_pack_version="0.1.3",
        )
    )
def _build_template(
    *,
    model_asset_id: str = "fake/default",
) -> WorkflowGraphTemplate:
    return WorkflowGraphTemplate(
        template_id="template-model-session",
        template_version="1.0.0",
        display_name="Model Session",
        nodes=(
            WorkflowGraphNode(
                node_id="loader",
                node_type_id="custom.fake.load-checkpoint",
                parameters={"model_asset_id": model_asset_id},
            ),
            WorkflowGraphNode(node_id="consumer", node_type_id="custom.fake.infer"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-model",
                source_node_id="loader",
                source_port="model",
                target_node_id="consumer",
                target_port="model",
            ),
        ),
    )


def _build_two_loader_template() -> WorkflowGraphTemplate:
    """构造两个彼此独立、可以并行准备的 loader。"""

    return WorkflowGraphTemplate(
        template_id="template-parallel-model-session",
        template_version="1.0.0",
        display_name="Parallel Model Session",
        nodes=(
            WorkflowGraphNode(
                node_id="loader-a",
                node_type_id="custom.fake.load-checkpoint",
                parameters={"model_asset_id": "fake/a"},
            ),
            WorkflowGraphNode(
                node_id="consumer-a",
                node_type_id="custom.fake.infer",
            ),
            WorkflowGraphNode(
                node_id="loader-b",
                node_type_id="custom.fake.load-checkpoint",
                parameters={"model_asset_id": "fake/b"},
            ),
            WorkflowGraphNode(
                node_id="consumer-b",
                node_type_id="custom.fake.infer",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-model-a",
                source_node_id="loader-a",
                source_port="model",
                target_node_id="consumer-a",
                target_port="model",
            ),
            WorkflowGraphEdge(
                edge_id="edge-model-b",
                source_node_id="loader-b",
                source_port="model",
                target_node_id="consumer-b",
                target_port="model",
            ),
        ),
    )
