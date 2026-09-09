"""backend-service 退出清理测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.service.api.bootstrap import BackendServiceBootstrap
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


def test_backend_shutdown_continues_after_trigger_stop_timeout() -> None:
    """Trigger 停止超时不能阻断 Workflow、LocalBuffer 与数据库清理。"""

    calls: list[str] = []

    class _TimedOutTriggerSupervisor:
        def stop_all(self) -> None:
            calls.append("triggers.stop_all")
            raise OperationTimeoutError("injected trigger stop timeout")

    workflow_context = SimpleNamespace(
        workflow_model_session_manager=None,
        workflow_storage_image_cache=None,
        close=lambda: calls.append("workflow_context.close"),
    )
    runtime = SimpleNamespace(
        queue_outbox_dispatcher=_Recorder("queue_outbox", calls),
        training_telemetry_receiver=None,
        training_telemetry_broker=_Recorder("training_broker", calls),
        trigger_source_supervisor=_TimedOutTriggerSupervisor(),
        workflow_trigger_mailbox_supervisor=None,
        deployment_runtime_reconciler=_Recorder("deployment_reconciler", calls),
        workflow_runtime_worker_manager=_Recorder("workflow_manager", calls),
        workflow_preview_sessions=_Recorder("preview_manager", calls),
        workflow_service_node_runtime_context=workflow_context,
        iter_all_deployment_supervisors=lambda: (),
        inference_message_client=None,
        local_buffer_broker_supervisor=_Recorder("local_buffer", calls),
        session_factory=SimpleNamespace(engine=_Recorder("database", calls)),
    )

    BackendServiceBootstrap().stop_runtime(runtime)

    assert calls == [
        "queue_outbox.stop",
        "training_broker.close",
        "triggers.stop_all",
        "deployment_reconciler.stop",
        "preview_manager.close",
        "workflow_manager.stop",
        "workflow_context.close",
        "local_buffer.stop",
        "database.dispose",
    ]
