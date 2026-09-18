"""服务就绪查询的隔离、生命周期和满载语义回归。"""

import json
import asyncio
from threading import Event, Lock
from time import monotonic, monotonic_ns
from types import SimpleNamespace as NS

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.service.application.service_status import ServiceStatusMonitor
from backend.service.application.service_status_collector import ServiceStatusCollector
from backend.service.application.workflows.worker.manager import (
    WorkflowRuntimeWorkerManager,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.api.rest.v1.routes.system.status import system_status_router
from backend.service.api.rest.v1.routes.system.status import get_service_status
from backend.service.application.errors import AuthenticationRequiredError, PermissionDeniedError
from backend.service.infrastructure.ipc.service_status_channel import (
    STATUS_PROFILE,
    InferenceStatusPublisher,
    read_inference_status,
    status_paths,
)
from backend.service.infrastructure.ipc.local_message.event_ring import (
    MmapEventRingPublisher,
)
from backend.service.infrastructure.http.drain_middleware import HttpDrainMiddleware
from backend.service.infrastructure.http.liveness import ServiceLiveness


def test_high_frequency_reads_never_recollect_and_stale_fails_closed(monkeypatch):
    """大量读取复用同一个 bytes，采集器失败、过期和停止撤销 ready。"""
    calls = []
    monitor = ServiceStatusMonitor(lambda: calls.append(1) or [], "boot")
    assert monitor.response()[0] == 503
    monitor.refresh()
    code, body = monitor.response()
    assert code == 200
    for _ in range(10000):
        assert monitor.response()[1] is body
    assert len(calls) == 1
    timestamp = monitor._snapshot[0]
    monkeypatch.setattr(
        "backend.service.application.service_status.monotonic", lambda: timestamp + 6
    )
    assert monitor.response()[0] == 503
    assert json.loads(monitor.response()[1])["blockers"][0]["code"] == "status_stale"
    monitor.collector = lambda: (_ for _ in ()).throw(RuntimeError("database down"))
    monitor.refresh()
    assert json.loads(monitor.response()[1])["summary"] is None
    assert monitor.response(stopping=True)[0] == 503


def test_status_api_uses_cached_bytes_and_no_store():
    """HTTP 状态、公开摘要及无缓存契约。"""
    app = FastAPI()
    app.include_router(system_status_router, prefix="/api/v1/system")
    app.state.service_liveness = ServiceLiveness(phase="ready")
    app.add_middleware(HttpDrainMiddleware, liveness=app.state.service_liveness)
    app.state.service_status_monitor = ServiceStatusMonitor(lambda: [], "boot")
    client = TestClient(app)
    assert client.get("/api/v1/system/status").status_code == 503
    app.state.service_status_monitor.refresh()
    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "resources" not in response.json()
    app.state.service_liveness.phase = "draining"
    assert client.get("/api/v1/system/status").json()["state"] == "stopping"


@pytest.mark.parametrize("scopes", [None, ("auth:read",), ("*",)])
def test_status_details_are_global_admin_only(monkeypatch, scopes):
    """全局数量不被项目权限过滤为假成功，资源 id 只对管理员返回。"""
    monkeypatch.setattr("backend.service.api.rest.v1.routes.system.status.resolve_request_principal",
                        lambda _: NS(scopes=scopes) if scopes is not None else None)
    monitor = ServiceStatusMonitor(lambda: [{"kind": "runtimes", "id": "private-runtime", "ready": True, "code": "ok"}], "boot")
    monitor.refresh()
    request = NS(app=NS(state=NS(service_status_monitor=monitor, service_liveness=NS(phase="ready"))))
    assert b"private-runtime" not in monitor.response()[1]
    if scopes is None:
        with pytest.raises(AuthenticationRequiredError):
            asyncio.run(get_service_status(request, details=True))
    elif scopes != ("*",):
        with pytest.raises(PermissionDeniedError):
            asyncio.run(get_service_status(request, details=True))
    else:
        assert b"private-runtime" in asyncio.run(get_service_status(request, details=True)).body


@pytest.mark.parametrize(
    "failure", [None, "process", "stale", "stopping", "response_thread"]
)
def test_runtime_busy_is_ready_but_failed_identity_lifecycle_is_not(failure):
    """执行锁被持有、长任务与繁忙状态不影响独立心跳判定。"""
    manager = object.__new__(WorkflowRuntimeWorkerManager)
    manager._lock = Lock()
    manager._stopping = Event()
    execution_lock = Lock()
    execution_lock.acquire()
    handle = NS(
        state_lock=Lock(),
        request_lock=execution_lock,
        expected_shutdown=failure == "stopping",
        process=NS(is_alive=lambda: failure != "process"),
        latest_runtime_state=NS(
            observed_state="running",
            current_run_id="long-run",
            loaded_snapshot_fingerprint="fp",
            last_error="busy earlier",
        ),
        latest_runtime_state_monotonic=monotonic() - (100 if failure == "stale" else 0),
        heartbeat_timeout_seconds=15,
        response_thread=NS(is_alive=lambda: failure != "response_thread"),
        workflow_runtime_revision_id="revision",
        runtime_generation=2,
    )
    manager._handles = {"runtime": handle}
    assert manager.service_status_snapshot()["runtime"]["ready"] is (failure is None)
    execution_lock.release()


@pytest.fixture
def collector(monkeypatch):
    """使用真实采集器并隔离持久化与组件，实现可控故障注入。"""
    revision = NS(state="active", generation=2, expected_snapshot_fingerprint="fp")
    workflow = NS(
        workflow_runtime_id="runtime",
        active_revision_id="rev",
        desired_revision_id="rev",
        revision_generation=2,
        template_snapshot_object_key="template",
    )
    trigger = NS(trigger_source_id="trigger", workflow_runtime_id="runtime")
    deployment = NS(deployment_instance_id="model", runtime_mode="sync")
    uow = NS(
        deployments=NS(
            get_deployment_instance=lambda _: NS(
                runtime_configuration=NS(instance_count=2)
            )
        ),
        deployment_runtime_states=NS(
            list_deployment_runtime_states=lambda **_: [deployment]
        ),
        workflow_runtime=NS(
            list_workflow_app_runtimes_by_desired_state=lambda _: [workflow],
            get_workflow_runtime_revision=lambda _: revision,
        ),
        workflow_trigger_sources=NS(list_enabled_trigger_sources=lambda: [trigger]),
        close=lambda: None,
    )
    monkeypatch.setattr(
        "backend.service.application.service_status_collector.SqlAlchemyUnitOfWork",
        lambda _: uow,
    )
    model = {
        "id": "model",
        "mode": "sync",
        "ready": True,
        "instance_count": 2,
        "busy": True,
    }
    daemon = {"ready": True, "deployments": [model]}
    monkeypatch.setattr(
        "backend.service.application.service_status_collector.read_inference_status",
        lambda _: daemon,
    )
    observed = {
        "runtime": {
            "ready": True,
            "revision_id": "rev",
            "generation": 2,
            "fingerprint": "fp",
        }
    }
    adapter = {"running": True, "busy_count": 100, "recent_error": "instance full"}
    runtime = NS(
        node_catalog_registry=NS(
            get_workflow_node_definitions=lambda: [
                NS(
                    node_type_id="core.model.classification",
                    runtime_requirements={"deployment_process": "sync"},
                )
            ]
        ),
        dataset_storage=NS(
            read_json=lambda _: {
                "nodes": [
                    {
                        "node_type_id": "core.model.classification",
                        "parameters": {"deployment_instance_id": "model"},
                    }
                ]
            }
        ),
        session_factory=NS(create_session=lambda: None),
        settings=NS(
            inference_daemon=NS(runtime_owner="daemon"),
            local_memory=NS(root_dir="unused"),
        ),
        local_buffer_broker_supervisor=NS(
            get_health_summary=lambda: {
                "enabled": True,
                "running": True,
                "state": "healthy",
            }
        ),
        workflow_runtime_worker_manager=NS(service_status_snapshot=lambda: observed),
        trigger_source_supervisor=NS(get_health=lambda _: {"adapter_health": adapter}),
    )
    return ServiceStatusCollector(runtime), model, daemon, observed, workflow, adapter


def test_collector_full_load_and_old_business_error_are_healthy(collector):
    """满载/旧错误不污染整体状态。"""
    collect, *_ = collector
    assert all(item["ready"] for item in collect())


def test_collector_partial_model_failure_and_old_runtime_revision(collector):
    """一项模型失败与旧版本 Worker 都不能伪装为全部成功。"""
    collect, model, _, observed, _, _ = collector
    model["ready"] = False
    assert not next(item for item in collect() if item["kind"] == "deployments")[
        "ready"
    ]
    observed["runtime"]["generation"] = 1
    rows = collect()
    assert not next(item for item in rows if item["kind"] == "runtimes")["ready"]
    assert not next(item for item in rows if item["kind"] == "triggers")["ready"]


def test_collector_requires_all_configured_model_instances(collector):
    """期望两个实例而当前只初始化一个，不能返回全就绪。"""
    collect, model, *_ = collector
    model["instance_count"] = 1
    assert not next(item for item in collect() if item["kind"] == "deployments")[
        "ready"
    ]


def test_missing_model_dependency_and_disabled_node(collector):
    """未启动的静态模型依赖阻止 Runtime 就绪；禁用节点不计入。"""
    collect, _, daemon, *_ = collector
    daemon["deployments"] = []
    rows = collect()
    assert (
        next(item for item in rows if item["kind"] == "runtimes")["code"]
        == "model_dependency_unavailable"
    )
    collect.runtime.dataset_storage.read_json = lambda _: {
        "nodes": [
            {
                "enabled": False,
                "node_type_id": "core.model.classification",
                "parameters": {"deployment_instance_id": "missing"},
            }
        ]
    }
    collect._dependencies.clear()
    assert (
        next(item for item in collect() if item["kind"] == "runtimes")["ready"] is True
    )


@pytest.mark.parametrize(
    "warmed,response_alive,expected",
    [(2, True, True), (1, True, False), (2, False, False)],
)
def test_model_snapshot_ignores_busy_and_requires_initialization(
    warmed, response_alive, expected
):
    """模型数据面不接收任何健康请求，繁忙实例仍就绪。"""
    supervisor = object.__new__(DeploymentProcessSupervisor)
    supervisor._lock = Lock()
    state = NS(
        lock=Lock(),
        config=NS(instance_count=2),
        warmed_instance_count=warmed,
        response_thread=NS(is_alive=lambda: response_alive),
        response_stop_event=Event(),
        pending_responses={"long-inference": object()},
        last_error="instance full",
    )
    supervisor._deployments = {"model": state}
    supervisor._build_status_from_locked_state = lambda _: NS(
        deployment_instance_id="model",
        runtime_mode="sync",
        instance_count=2,
        process_state="running",
    )
    assert supervisor.service_status_snapshot()[0]["ready"] is expected


def test_status_channel_owner_death_staleness_and_restart(tmp_path):
    """独立 EventRing 不需要推理容量；拒绝过期、关闭及旧 epoch。"""
    publisher = MmapEventRingPublisher(
        paths=status_paths(str(tmp_path)), profile=STATUS_PROFILE
    )
    try:
        publisher.try_publish(
            json.dumps({"ready": True, "observed_ns": monotonic_ns()}).encode()
        )
        assert read_inference_status(str(tmp_path))["ready"] is True
        publisher.try_publish(
            json.dumps(
                {"ready": True, "observed_ns": monotonic_ns() - 6_000_000_000}
            ).encode()
        )
        with pytest.raises(RuntimeError, match="过期"):
            read_inference_status(str(tmp_path))
    finally:
        publisher.close(deadline_ns=monotonic_ns())
    with pytest.raises(RuntimeError, match="不可用"):
        read_inference_status(str(tmp_path))
    publisher = InferenceStatusPublisher(
        str(tmp_path), lambda: {"ready": True, "deployments": []}
    )
    publisher.start()
    try:
        # 等待独立发布线程完成首次状态写入，最多一秒。
        deadline = monotonic() + 1
        while monotonic() < deadline:
            try:
                if read_inference_status(str(tmp_path)).get("ready"):
                    break
            except RuntimeError:
                Event().wait(0.01)
        else:
            pytest.fail("状态发布线程未启动")
    finally:
        publisher.stop()
    assert not publisher._thread.is_alive()
