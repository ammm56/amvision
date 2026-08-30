"""本机共享内存 Trigger route、source permit 与有界 executor 测试。"""

from __future__ import annotations

from threading import Event

import pytest

from backend.service.application.errors import (
    InvalidRequestError,
    WorkflowTriggerExecutorBusyError,
    WorkflowTriggerSourceBusyError,
)
from backend.service.application.workflows.trigger_sources.local_shared_runtime import (
    BoundedWorkflowTriggerExecutor,
    WorkflowTriggerRouteRegistry,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    TRIGGER_RESPONSE_PLAN_METADATA_KEY,
    build_trigger_response_plan,
)
from backend.service.application.workflows.trigger_sources.trigger_source_service import (
    _build_supervisor_health_summary,
)
from backend.service.infrastructure.integrations.local_shared_memory.local_shared_memory_trigger_adapter import (
    LocalSharedMemoryTriggerAdapter,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


def test_idle_sources_only_use_route_metadata() -> None:
    """100 个 idle source 只登记路由，不预占任何执行或图片容量。"""

    registry = WorkflowTriggerRouteRegistry()
    for index in range(100):
        registry.register(_source(f"source-{index}"))

    assert registry.build_status() == {
        "route_count": 100,
        "active_source_permit_count": 0,
    }


def test_same_source_is_single_flight_and_stale_release_is_fenced() -> None:
    """同一 source 第二条立即 busy，伪造或迟到 permit 不能释放当前调用。"""

    registry = WorkflowTriggerRouteRegistry()
    route = registry.register(_source("source-1"))
    permit = registry.acquire_source_permit(route=route, request_id="request-1")

    with pytest.raises(WorkflowTriggerSourceBusyError):
        registry.acquire_source_permit(route=route, request_id="request-2")

    stale = permit.__class__(
        permit_id="stale",
        trigger_source_id=permit.trigger_source_id,
        route_generation=permit.route_generation,
        request_id=permit.request_id,
    )
    assert registry.release_source_permit(stale) is False
    assert registry.release_source_permit(permit) is True
    assert registry.acquire_source_permit(
        route=route,
        request_id="request-2",
    ).request_id == "request-2"


def test_different_sources_can_be_in_flight_together() -> None:
    """单在途限制按 source 隔离，不建立全局图片调用锁。"""

    registry = WorkflowTriggerRouteRegistry()
    first_route = registry.register(_source("source-1"))
    second_route = registry.register(_source("source-2"))

    registry.acquire_source_permit(route=first_route, request_id="request-1")
    registry.acquire_source_permit(route=second_route, request_id="request-2")

    assert registry.build_status()["active_source_permit_count"] == 2


def test_route_generation_changes_only_when_route_semantics_change() -> None:
    """相同快照保持 generation，Runtime 或映射变化时推进。"""

    registry = WorkflowTriggerRouteRegistry()
    source = _source("source-1")
    first = registry.register(source)
    same = registry.register(source)
    changed = registry.register(
        _source(
            "source-1",
            workflow_runtime_id="runtime-2",
            previous_metadata=source.metadata,
        )
    )

    assert same.route_generation == first.route_generation
    assert changed.route_generation == first.route_generation + 1
    with pytest.raises(InvalidRequestError, match="generation"):
        registry.get_route(
            trigger_source_id=source.trigger_source_id,
            expected_generation=first.route_generation,
        )


def test_executor_rejects_before_submit_and_never_queues() -> None:
    """worker 正在执行时，第二条不进入 ThreadPoolExecutor 内部队列。"""

    entered = Event()
    release = Event()
    executor = BoundedWorkflowTriggerExecutor(max_workers=1)
    try:
        first = executor.submit(lambda: _block(entered, release))
        assert entered.wait(timeout=2.0)
        with pytest.raises(WorkflowTriggerExecutorBusyError):
            executor.submit(lambda: "must-not-run")
        assert executor.build_status()["active_count"] == 1

        release.set()
        assert first.result(timeout=2.0) == "done"
        assert executor.submit(lambda: "next").result(timeout=2.0) == "next"
    finally:
        release.set()
        executor.shutdown()


def test_executor_reservation_precedes_worker_submit() -> None:
    """permit 可以先于 owner transfer 预留，失败补偿后容量立即恢复。"""

    executor = BoundedWorkflowTriggerExecutor(max_workers=1)
    try:
        permit = executor.reserve()
        with pytest.raises(WorkflowTriggerExecutorBusyError):
            executor.reserve()
        assert executor.release_reserved(permit) is True
        assert executor.release_reserved(permit) is False
        assert executor.submit(lambda: "ok").result(timeout=2.0) == "ok"
    finally:
        executor.shutdown()


def test_local_shared_memory_adapter_uses_common_running_health_field() -> None:
    """本机共享内存 adapter 与 supervisor 公共 health 契约使用同一 running 字段。"""

    supervisor = _FakeMailboxSupervisor()
    adapter = LocalSharedMemoryTriggerAdapter(mailbox_supervisor=supervisor)  # type: ignore[arg-type]
    source = _source("source-health")

    adapter.start(trigger_source=source, event_handler=object())  # type: ignore[arg-type]

    assert adapter.get_health(trigger_source_id=source.trigger_source_id) == {
        "adapter_kind": "local-shared-memory",
        "source_scoped": True,
        "running": True,
        "route_generation": 7,
        "last_triggered_at": "2026-08-30T10:20:30+00:00",
        "pending_request_count": 0,
        "active_task_count": 0,
        "request_count": 5,
        "success_count": 4,
        "error_count": 1,
        "timeout_count": 0,
        "busy_count": 1,
        "capacity_reject_count": 2,
        "request_timeout_count": 0,
        "response_ack_timeout_count": 0,
        "cancel_count": 3,
        "recent_error": None,
        "idle_poll_sleep_count": 8,
        "mailbox": {"used_page_count": 0},
        "executor": {"active_count": 0},
        "recent_poller_error": None,
        "recent_request_error": None,
        "latest_timings": {"total_ms": 12.5},
    }


def test_supervisor_health_summary_uses_source_live_trigger_time() -> None:
    """source 内存态时间必须进入控制面摘要，且不依赖数据库写入。"""

    summary = _build_supervisor_health_summary(
        supervisor_health={
            "adapter_health": {
                "source_scoped": True,
                "running": True,
                "last_triggered_at": "2026-08-30T10:20:30+00:00",
            }
        },
        adapter_configured=True,
    )

    assert summary["last_triggered_at"] == "2026-08-30T10:20:30+00:00"


def _source(
    trigger_source_id: str,
    *,
    workflow_runtime_id: str = "runtime-1",
    previous_metadata: dict[str, object] | None = None,
) -> WorkflowTriggerSource:
    """创建已启用的本机共享内存 source。"""

    response_plan = build_trigger_response_plan(
        trigger_source_id=trigger_source_id,
        trigger_kind="local-shared-memory",
        workflow_runtime_id=workflow_runtime_id,
        workflow_runtime_revision_id="revision-1",
        workflow_app_version_id="version-1",
        workflow_runtime_generation=1,
        expected_snapshot_fingerprint="snapshot-1",
        contract_fingerprint="contract-1",
        submit_mode="sync",
        result_mode="sync-reply",
        ack_policy="ack-after-run-finished",
        reply_timeout_seconds=30,
        response_ack_timeout_seconds=30.0,
        selected_output_payload_types={},
        previous_plan=(previous_metadata or {}).get(
            TRIGGER_RESPONSE_PLAN_METADATA_KEY
        ),
    )

    return WorkflowTriggerSource(
        trigger_source_id=trigger_source_id,
        project_id="project-1",
        display_name=trigger_source_id,
        trigger_kind="local-shared-memory",
        workflow_runtime_id=workflow_runtime_id,
        submit_mode="sync",
        enabled=True,
        desired_state="running",
        observed_state="running",
        reply_timeout_seconds=30,
        metadata={
            TRIGGER_RESPONSE_PLAN_METADATA_KEY: response_plan.model_dump(mode="json")
        },
    )


def _block(entered: Event, release: Event) -> str:
    """占住单个 executor worker。"""

    entered.set()
    assert release.wait(timeout=2.0)
    return "done"


class _FakeMailboxSupervisor:
    """提供 adapter health 测试需要的最小 mailbox supervisor。"""

    def register_trigger_source(self, trigger_source: WorkflowTriggerSource) -> object:
        del trigger_source
        return type("Route", (), {"route_generation": 7})()

    def unregister_trigger_source(self, trigger_source_id: str) -> None:
        del trigger_source_id

    def build_status(self) -> dict[str, object]:
        return {
            "running": True,
            "pending_request_count": 0,
            "active_task_count": 0,
            "completed_request_count": 4,
            "failed_request_count": 1,
            "idle_poll_sleep_count": 8,
            "mailbox": {"used_page_count": 0},
            "executor": {"active_count": 0},
            "recent_poller_error": None,
            "recent_request_error": None,
            "latest_timings": {"total_ms": 12.5},
        }

    def build_source_status(self, trigger_source_id: str) -> dict[str, object]:
        assert trigger_source_id == "source-health"
        return {
            "source_scoped": True,
            "last_triggered_at": "2026-08-30T10:20:30+00:00",
            "pending_request_count": 0,
            "active_task_count": 0,
            "request_count": 5,
            "success_count": 4,
            "error_count": 1,
            "timeout_count": 0,
            "busy_count": 1,
            "capacity_reject_count": 2,
            "request_timeout_count": 0,
            "response_ack_timeout_count": 0,
            "cancel_count": 3,
            "recent_error": None,
        }
