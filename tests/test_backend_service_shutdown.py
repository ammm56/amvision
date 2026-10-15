"""backend-service 退出清理测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.service.api.bootstrap import BackendServiceBootstrap, BackendServiceRuntime
from backend.bootstrap.core import RuntimeLifecycle
from backend.service.application.errors import OperationTimeoutError


class _Recorder:
    """记录 stop、close、dispose 调用的测试替身。"""

    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def stop(self) -> None:
        self.calls.append(f"{self.name}.stop")

    def close(self) -> None:
        self.calls.append(f"{self.name}.close")

    def dispose(self) -> None:
        self.calls.append(f"{self.name}.dispose")


def test_backend_visits_every_task_type_supervisor():
    """不同任务类型的字段命名不能导致八个 sync/async supervisor 被漏掉。"""
    names = ["detection_sync_deployment_process_supervisor",
             "detection_async_deployment_process_supervisor",
             "detection_async_inference_gateway_dispatcher_registry"]
    for task in ("classification", "segmentation", "pose", "obb"):
        names.extend((f"{task}_sync_deployment_supervisor",
                      f"{task}_async_deployment_supervisor",
                      f"{task}_async_inference_gateway_registry"))
    runtime = SimpleNamespace(**{name: object() for name in names})
    assert list(BackendServiceRuntime.iter_all_deployment_supervisors(runtime)) == [getattr(runtime, name) for name in names]


@pytest.mark.parametrize("failure", ["outbox", "telemetry", "trigger", "reconciler"])
def test_backend_shutdown_preserves_dependencies_after_trigger_stop_timeout(failure) -> None:
    """Trigger 未确认退出时保留其依赖，不能提前关闭 Workflow 与数据库。"""

    calls: list[str] = []
    failing = {"active": True}

    class _Producer(_Recorder):
        def stop(self):
            super().stop()
            if failure == self.name and failing["active"]:
                raise OperationTimeoutError("injected stop timeout")

    class _TimedOutTriggerSupervisor:
        def stop_all(self) -> None:
            calls.append("triggers.stop_all")
            if failure == "trigger" and failing["active"]:
                raise OperationTimeoutError("injected trigger stop timeout")

    workflow_context = SimpleNamespace(
        workflow_model_session_manager=None,
        workflow_storage_image_cache=None,
        close=lambda: calls.append("workflow_context.close"),
    )
    runtime = SimpleNamespace(
        lifecycle=RuntimeLifecycle(),
        queue_outbox_dispatcher=_Producer("outbox", calls),
        training_telemetry_receiver=_Producer("telemetry", calls),
        training_telemetry_broker=_Recorder("training_broker", calls),
        trigger_source_supervisor=_TimedOutTriggerSupervisor(),
        workflow_trigger_mailbox_supervisor=None,
        deployment_runtime_reconciler=_Producer("reconciler", calls),
        workflow_runtime_worker_manager=_Recorder("workflow_manager", calls),
        workflow_preview_sessions=_Recorder("preview_manager", calls),
        workflow_service_node_runtime_context=workflow_context,
        iter_all_deployment_supervisors=lambda: (),
        inference_message_client=None,
        local_buffer_broker_supervisor=_Recorder("local_buffer", calls),
        session_factory=SimpleNamespace(engine=_Recorder("database", calls)),
    )

    with pytest.raises(OperationTimeoutError):
        BackendServiceBootstrap().stop_runtime(runtime)

    expected = ["outbox.stop", "telemetry.stop", "training_broker.close", "triggers.stop_all", "reconciler.stop"]
    assert calls == expected[:{"outbox": 1, "telemetry": 2, "trigger": 4, "reconciler": 5}[failure]]
    with pytest.raises(RuntimeError, match="停止"):
        BackendServiceBootstrap().start_runtime(runtime)
    failing["active"] = False
    BackendServiceBootstrap().stop_runtime(runtime)
    assert calls[-2:] == ["local_buffer.stop", "database.dispose"]
    completed = list(calls)
    BackendServiceBootstrap().stop_runtime(runtime)
    assert calls == completed
