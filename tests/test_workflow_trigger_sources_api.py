"""WorkflowTriggerSource 管理 API 测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import build_test_headers, create_api_test_context


def test_workflow_trigger_source_api_manages_first_phase_resource(
    tmp_path: Path,
) -> None:
    """验证 TriggerSource 管理 API 可以创建、查询、启用、停用并删除后重建资源。"""

    context = create_api_test_context(
        tmp_path, database_name="workflow-trigger-sources.db"
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with context.client:
            _save_runtime(context.session_factory, observed_state="stopped")
            create_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "trigger-source-1",
                    "project_id": "project-1",
                    "display_name": "HTTP Baseline Trigger",
                    "trigger_kind": "http-api",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "input_binding_mapping": {
                        "request_image": {"source": "payload.image"},
                    },
                    "result_mapping": {
                        "result_binding": "http_response",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            create_second_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "trigger-source-2",
                    "project_id": "project-1",
                    "display_name": "HTTP Secondary Trigger",
                    "trigger_kind": "http-api",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "input_binding_mapping": {
                        "request_image": {"source": "payload.image"},
                    },
                    "result_mapping": {
                        "result_binding": "http_response",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            list_response = context.client.get(
                "/api/v1/workflows/trigger-sources?project_id=project-1&offset=0&limit=1",
                headers=headers,
            )
            get_response = context.client.get(
                "/api/v1/workflows/trigger-sources/trigger-source-1",
                headers=headers,
            )
            health_response = context.client.get(
                "/api/v1/workflows/trigger-sources/trigger-source-1/health",
                headers=headers,
            )
            enable_stopped_response = context.client.post(
                "/api/v1/workflows/trigger-sources/trigger-source-1/enable",
                headers=headers,
            )
            _save_runtime(context.session_factory, observed_state="running")
            enable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/trigger-source-1/enable",
                headers=headers,
            )
            disable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/trigger-source-1/disable",
                headers=headers,
            )
            delete_response = context.client.delete(
                "/api/v1/workflows/trigger-sources/trigger-source-1",
                headers=headers,
            )
            get_deleted_response = context.client.get(
                "/api/v1/workflows/trigger-sources/trigger-source-1",
                headers=headers,
            )
            recreate_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "trigger-source-1",
                    "project_id": "project-1",
                    "display_name": "HTTP Baseline Trigger Recreated",
                    "trigger_kind": "http-api",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "input_binding_mapping": {
                        "request_image": {"source": "payload.image"},
                    },
                    "result_mapping": {
                        "result_binding": "http_response",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201
    assert create_second_response.status_code == 201
    create_payload = create_response.json()
    assert create_payload["format_id"] == "amvision.workflow-trigger-source.v1"
    assert create_payload["trigger_source_id"] == "trigger-source-1"
    assert create_payload["enabled"] is False
    assert create_payload["observed_state"] == "stopped"
    assert create_payload["updated_by"] == "user-1"
    assert create_payload["runtime_summary"]["workflow_runtime_id"] == "workflow-runtime-1"
    assert create_payload["application_summary"] is None

    assert list_response.status_code == 200
    assert list_response.headers["x-offset"] == "0"
    assert list_response.headers["x-limit"] == "1"
    assert list_response.headers["x-total-count"] == "2"
    assert list_response.headers["x-has-more"] == "true"
    assert list_response.headers["x-next-offset"] == "1"
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["trigger_source_id"] == "trigger-source-2"
    assert get_response.status_code == 200
    assert get_response.json()["result_mapping"]["result_binding"] == "http_response"

    assert health_response.status_code == 200
    assert health_response.json()["health_summary"]["adapter_configured"] is False

    assert enable_stopped_response.status_code == 400
    assert enable_stopped_response.json()["error"]["code"] == "invalid_request"

    assert enable_response.status_code == 200
    assert enable_response.json()["enabled"] is True
    assert enable_response.json()["desired_state"] == "running"
    assert enable_response.json()["updated_by"] == "user-1"

    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
    assert disable_response.json()["desired_state"] == "stopped"
    assert disable_response.json()["updated_by"] == "user-1"

    assert delete_response.status_code == 204

    assert get_deleted_response.status_code == 404
    assert get_deleted_response.json()["error"]["code"] == "resource_not_found"

    assert recreate_response.status_code == 201
    assert recreate_response.json()["display_name"] == "HTTP Baseline Trigger Recreated"


def test_workflow_trigger_source_api_controls_zeromq_adapter(
    tmp_path: Path,
) -> None:
    """验证 TriggerSource 管理 API 可以删除并重建 ZeroMQ TriggerSource。"""

    context = create_api_test_context(
        tmp_path, database_name="workflow-trigger-sources-zeromq.db"
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    bind_endpoint = f"inproc://workflow-trigger-source-{uuid4().hex}"
    try:
        with context.client:
            _save_runtime(context.session_factory, observed_state="running")
            create_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "zeromq-trigger-source-1",
                    "project_id": "project-1",
                    "display_name": "ZeroMQ Trigger",
                    "trigger_kind": "zeromq-topic",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "transport_config": {"bind_endpoint": bind_endpoint},
                    "input_binding_mapping": {
                        "request_image": {"source": "payload.buffer_ref"},
                    },
                    "result_mapping": {
                        "result_binding": "zeromq_reply",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            enable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/zeromq-trigger-source-1/enable",
                headers=headers,
            )
            health_response = context.client.get(
                "/api/v1/workflows/trigger-sources/zeromq-trigger-source-1/health",
                headers=headers,
            )
            disable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/zeromq-trigger-source-1/disable",
                headers=headers,
            )
            delete_response = context.client.delete(
                "/api/v1/workflows/trigger-sources/zeromq-trigger-source-1",
                headers=headers,
            )
            recreate_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "zeromq-trigger-source-1",
                    "project_id": "project-1",
                    "display_name": "ZeroMQ Trigger Recreated",
                    "trigger_kind": "zeromq-topic",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "transport_config": {"bind_endpoint": bind_endpoint},
                    "input_binding_mapping": {
                        "request_image": {"source": "payload.buffer_ref"},
                    },
                    "result_mapping": {
                        "result_binding": "zeromq_reply",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201

    assert enable_response.status_code == 200
    enable_payload = enable_response.json()
    assert enable_payload["enabled"] is True
    assert enable_payload["observed_state"] == "running"
    assert enable_payload["updated_by"] == "user-1"
    assert enable_payload["health_summary"]["adapter_configured"] is True
    assert enable_payload["health_summary"]["adapter_running"] is True

    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["observed_state"] == "running"
    assert health_payload["health_summary"]["adapter_running"] is True

    assert disable_response.status_code == 200
    disable_payload = disable_response.json()
    assert disable_payload["enabled"] is False
    assert disable_payload["desired_state"] == "stopped"
    assert disable_payload["health_summary"]["adapter_configured"] is True
    assert disable_payload["health_summary"]["adapter_running"] is False

    assert delete_response.status_code == 204

    assert recreate_response.status_code == 201
    assert recreate_response.json()["display_name"] == "ZeroMQ Trigger Recreated"


def _save_runtime(session_factory: SessionFactory, *, observed_state: str) -> None:
    """保存测试使用的 WorkflowAppRuntime。

    参数：
    - session_factory：测试数据库会话工厂。
    - observed_state：要写入的 runtime 观测状态。
    """

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id="workflow-runtime-1",
                project_id="project-1",
                application_id="app-1",
                display_name="App Runtime",
                application_snapshot_object_key="app.json",
                template_snapshot_object_key="template.json",
                desired_state="running" if observed_state == "running" else "stopped",
                observed_state=observed_state,
                created_at="2026-05-13T00:00:00Z",
                updated_at="2026-05-13T00:00:00Z",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
