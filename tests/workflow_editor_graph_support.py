"""节点业务测试直接使用内存快照执行器；完整进程/WS 测试另行覆盖。"""

from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

from backend.service.application.errors import ServiceError, OperationTimeoutError, OperationCancelledError
from backend.service.application.workflows.preview.execution import PreviewMemoryExecutionRequest, PreviewMemoryExecutionService


def run_memory_preview(client, headers, *, project_id, application, template, input_bindings, timeout_seconds=30):
    """协议集成测试使用最新 REST 受理和 WS 终态，不模拟旧运行资源。"""
    base = "/api/v1/workflows/preview-sessions"
    created = client.post(base, headers=headers, json={"project_id": project_id,
        "application_id": application.application_id, "editor_session_id": str(uuid4())})
    assert created.status_code == 201, created.text
    sid = created.json()["session_id"]
    try:
        with client.websocket_connect(f"/ws/v1/workflows/preview-sessions/{sid}", headers=headers) as ws:
            assert ws.receive_json()["type"] == "session.snapshot"
            accepted = client.post(f"{base}/{sid}/runs", headers=headers, json={
                "request_id": str(uuid4()), "document_revision": "integration", "application": application.model_dump(mode="json"),
                "template": template.model_dump(mode="json"), "input_bindings": input_bindings, "timeout_seconds": timeout_seconds})
            assert accepted.status_code == 202, accepted.text
            while True:
                event = ws.receive_json()
                if event["type"] == "run.finished":
                    return {"state": event["payload"]["status"], **event["payload"]}
    finally:
        assert client.delete(f"{base}/{sid}", headers=headers).status_code == 204


def execute_editor_graph(service, *, project_id, application, template, input_bindings=None,
                         timeout_seconds=None, execution_scope_kind="application", target_node_id=None, execution_metadata=None):
    """测试已有节点业务，不模拟已删除的 REST、持久化记录或事件文件。"""
    events = []
    metadata = {"retain_node_records_enabled": True, **(execution_metadata or {})}
    if timeout_seconds is not None:
        from backend.service.application.workflows.execution_cleanup import WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY
        metadata[WORKFLOW_EXECUTION_TIMEOUT_SECONDS_KEY] = timeout_seconds
    try:
        result = PreviewMemoryExecutionService(
            dataset_storage=service.dataset_storage, node_catalog_registry=service.node_catalog_registry,
            runtime_registry=service.workflow_node_runtime_registry,
            runtime_context=service.workflow_service_node_runtime_context, event_sink=events.append,
        ).execute(PreviewMemoryExecutionRequest(project_id=project_id, application_id=application.application_id,
            application=application, template=template, session_id=uuid4().hex, input_bindings=input_bindings or {},
            execution_metadata=metadata, target_node_id=target_node_id if execution_scope_kind=="node" else None))
        return SimpleNamespace(state="succeeded", outputs=result.outputs, template_outputs=result.template_outputs,
            node_records=[asdict(record) for record in result.node_records], error_message=None, metadata={})
    except ServiceError as error:
        return SimpleNamespace(state="timed_out" if isinstance(error,OperationTimeoutError) else "cancelled" if isinstance(error,OperationCancelledError) else "failed",
            outputs={}, template_outputs={}, error_message=str(error),
            node_records=[event["payload"] for event in events if event["event_type"]=="node.completed"],
            metadata={"last_error":{"code":error.code,"message":str(error),"details":error.details}})
