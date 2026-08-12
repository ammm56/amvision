"""Workflow ResourceScope 与有界资源池测试。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from backend.service.application.runtime.resource_pool import BoundedResourcePool
from backend.service.application.runtime.resource_scope import (
    WORKFLOW_RESOURCE_SCOPE_METADATA_KEY,
    ResourceScope,
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.execution_cleanup import (
    build_process_safe_execution_metadata,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.camera_nodes.providers.usb_uvc.backend.runtime.resource_scope import (
    register_camera_session_resource,
    unregister_camera_session_resource,
)


def test_resource_scope_closes_in_reverse_order_and_is_idempotent() -> None:
    """资源应按逆序关闭，重复关闭不重复执行 closer。"""

    closed: list[str] = []
    scope = ResourceScope(kind="workflow")
    scope.register("first", "first", lambda value: closed.append(str(value)))
    scope.register("second", "second", lambda value: closed.append(str(value)))

    assert scope.close() == ()
    assert scope.close() == ()
    assert closed == ["second", "first"]


def test_workflow_scope_is_removed_from_process_safe_metadata() -> None:
    """进程内 ResourceScope 不能进入 multiprocessing Queue。"""

    metadata: dict[str, object] = {"workflow_run_id": "run-1"}
    scope = get_or_create_workflow_resource_scope(metadata)

    safe_metadata = build_process_safe_execution_metadata(metadata)

    assert metadata[WORKFLOW_RESOURCE_SCOPE_METADATA_KEY] is scope
    assert WORKFLOW_RESOURCE_SCOPE_METADATA_KEY not in safe_metadata


@dataclass
class _FakeResource:
    """记录关闭状态的测试资源。"""

    name: str


def test_bounded_resource_pool_reuses_and_evicts_lru_resource() -> None:
    """有界池复用相同 key，并在容量满时淘汰最早空闲项。"""

    created: list[str] = []
    closed: list[str] = []
    pool: BoundedResourcePool[_FakeResource] = BoundedResourcePool(
        max_entries=2,
        max_idle_seconds=60.0,
    )

    def acquire(name: str):
        return pool.acquire(
            name,
            lambda: created.append(name) or _FakeResource(name),
            lambda resource: closed.append(resource.name),
        )

    first = acquire("first")
    first.release()
    reused = acquire("first")
    reused.release()
    second = acquire("second")
    second.release()
    third = acquire("third")
    third.release()

    assert created == ["first", "second", "third"]
    assert closed == ["first"]
    assert pool.entry_count == 2
    pool.close()
    assert sorted(closed) == ["first", "second", "third"]


def test_resource_pool_defers_close_until_active_lease_returns() -> None:
    """Process scope 关闭时，正在使用的资源应在归还后关闭。"""

    closed: list[str] = []
    pool: BoundedResourcePool[_FakeResource] = BoundedResourcePool(
        max_entries=1,
        max_idle_seconds=60.0,
    )
    lease = pool.acquire(
        "active",
        lambda: _FakeResource("active"),
        lambda resource: closed.append(resource.name),
    )

    pool.close()
    assert closed == []
    lease.release()
    assert closed == ["active"]


def test_camera_session_resource_closes_with_workflow_scope() -> None:
    """未显式关闭的 Camera session 应由 Workflow scope 兜底关闭。"""

    metadata: dict[str, object] = {}
    request = WorkflowNodeExecutionRequest(
        node_id="open-camera",
        node_definition=SimpleNamespace(node_type_id="custom.camera.open"),
        execution_metadata=metadata,
    )
    session_entry = object()
    closed_session_ids: list[str] = []
    register_camera_session_resource(
        request,
        session_entry=session_entry,
        session_payload={"session_id": "camera-1"},
        closer=lambda cleanup_request: closed_session_ids.append(
            str(cleanup_request.input_values["session"]["session_id"])
        ),
    )

    get_or_create_workflow_resource_scope(metadata).close()

    assert closed_session_ids == ["camera-1"]


def test_explicit_camera_close_unregisters_workflow_fallback() -> None:
    """显式关闭成功后不应在 Workflow 结束时重复关闭 Camera。"""

    metadata: dict[str, object] = {}
    request = WorkflowNodeExecutionRequest(
        node_id="close-camera",
        node_definition=SimpleNamespace(node_type_id="custom.camera.close"),
        execution_metadata=metadata,
    )
    session_entry = object()
    close_count = 0

    def close_camera(_cleanup_request: WorkflowNodeExecutionRequest) -> None:
        nonlocal close_count
        close_count += 1

    register_camera_session_resource(
        request,
        session_entry=session_entry,
        session_payload={"session_id": "camera-1"},
        closer=close_camera,
    )
    unregister_camera_session_resource(request, session_entry=session_entry)
    get_or_create_workflow_resource_scope(metadata).close()

    assert close_count == 0
