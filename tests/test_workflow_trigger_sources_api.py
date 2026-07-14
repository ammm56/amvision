"""WorkflowTriggerSource 管理 API 测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.service.infrastructure.integrations.modbus import ModbusBitsReadResponse
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import (
    build_test_headers,
    create_api_test_context,
    get_default_test_principal_id,
)


def test_workflow_trigger_source_api_manages_first_phase_resource(
    tmp_path: Path,
) -> None:
    """验证 TriggerSource 管理 API 可以创建、查询、启用、停用并删除后重建资源。"""

    context = create_api_test_context(
        tmp_path,
        database_name="workflow-trigger-sources.db",
        enable_local_buffer_broker=False,
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
                        "request_image_base64": {"source": "payload.image"},
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
                        "request_image_base64": {"source": "payload.image"},
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
            failed_get_response = context.client.get(
                "/api/v1/workflows/trigger-sources/trigger-source-1",
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
                        "request_image_base64": {"source": "payload.image"},
                    },
                    "result_mapping": {
                        "result_binding": "http_response",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            default_principal_id = get_default_test_principal_id(context.session_factory)
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201
    assert create_second_response.status_code == 201
    create_payload = create_response.json()
    assert create_payload["format_id"] == "amvision.workflow-trigger-source.v1"
    assert create_payload["trigger_source_id"] == "trigger-source-1"
    assert create_payload["enabled"] is False
    assert create_payload["observed_state"] == "stopped"
    assert create_payload["updated_by"] == default_principal_id
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
    health_payload = health_response.json()
    assert health_payload["trigger_source_id"] == "trigger-source-1"
    assert health_payload["enabled"] is False
    assert health_payload["health_summary"]["adapter_configured"] is False
    assert health_payload["health_summary"]["request_count"] == 0

    assert enable_stopped_response.status_code == 400
    assert enable_stopped_response.json()["error"]["code"] == "invalid_request"

    assert enable_response.status_code == 400
    assert enable_response.json()["error"]["code"] == "invalid_request"
    assert enable_response.json()["error"]["details"]["trigger_kind"] == "http-api"

    assert failed_get_response.status_code == 200
    failed_payload = failed_get_response.json()
    assert failed_payload["enabled"] is True
    assert failed_payload["desired_state"] == "running"
    assert failed_payload["observed_state"] == "failed"
    assert failed_payload["last_error"] == "当前 TriggerSource 类型尚未接入可用 adapter，无法启用"
    assert failed_payload["health_summary"]["adapter_configured"] is False
    assert failed_payload["health_summary"]["recent_error"]["trigger_kind"] == "http-api"

    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
    assert disable_response.json()["desired_state"] == "stopped"
    assert disable_response.json()["updated_by"] == default_principal_id

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
        tmp_path,
        database_name="workflow-trigger-sources-zeromq.db",
        enable_local_buffer_broker=False,
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
                        "request_image_ref": {"source": "payload.buffer_ref"},
                    },
                    "result_mapping": {
                        "result_binding": "zeromq_reply",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            create_duplicate_endpoint_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "zeromq-trigger-source-2",
                    "project_id": "project-1",
                    "display_name": "ZeroMQ Trigger Duplicate Endpoint",
                    "trigger_kind": "zeromq-topic",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "transport_config": {"bind_endpoint": bind_endpoint},
                    "input_binding_mapping": {
                        "request_image_ref": {"source": "payload.buffer_ref"},
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
                        "request_image_ref": {"source": "payload.buffer_ref"},
                    },
                    "result_mapping": {
                        "result_binding": "zeromq_reply",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            default_principal_id = get_default_test_principal_id(context.session_factory)
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201
    assert create_duplicate_endpoint_response.status_code == 400
    duplicate_endpoint_payload = create_duplicate_endpoint_response.json()
    assert duplicate_endpoint_payload["error"]["code"] == "invalid_request"
    assert (
        duplicate_endpoint_payload["error"]["details"]["bind_endpoint"]
        == bind_endpoint
    )
    assert (
        duplicate_endpoint_payload["error"]["details"]["conflict_trigger_source_id"]
        == "zeromq-trigger-source-1"
    )

    assert enable_response.status_code == 200
    enable_payload = enable_response.json()
    assert enable_payload["enabled"] is True
    assert enable_payload["observed_state"] == "running"
    assert enable_payload["updated_by"] == default_principal_id
    assert enable_payload["health_summary"]["adapter_configured"] is True
    assert enable_payload["health_summary"]["adapter_running"] is True

    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["observed_state"] == "running"
    assert health_payload["health_summary"]["adapter_running"] is True
    assert isinstance(health_payload["health_summary"]["supervisor"], dict)

    assert disable_response.status_code == 200
    disable_payload = disable_response.json()
    assert disable_payload["enabled"] is False
    assert disable_payload["desired_state"] == "stopped"
    assert disable_payload["health_summary"]["adapter_configured"] is True
    assert disable_payload["health_summary"]["adapter_running"] is False

    assert delete_response.status_code == 204

    assert recreate_response.status_code == 201
    assert recreate_response.json()["display_name"] == "ZeroMQ Trigger Recreated"


def test_workflow_trigger_source_api_defaults_to_sync_reply(
    tmp_path: Path,
) -> None:
    """验证 TriggerSource 创建接口默认使用同步实时回包语义。"""

    context = create_api_test_context(
        tmp_path,
        database_name="workflow-trigger-source-defaults.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with context.client:
            _save_runtime(context.session_factory, observed_state="running")
            create_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "zeromq-trigger-source-defaults",
                    "project_id": "project-1",
                    "display_name": "ZeroMQ Trigger Defaults",
                    "trigger_kind": "zeromq-topic",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "transport_config": {
                        "bind_endpoint": f"inproc://workflow-trigger-defaults-{uuid4().hex}",
                        "default_input_binding": "request_image_ref",
                    },
                    "input_binding_mapping": {
                        "request_image_base64": {
                            "source": "payload.request_image_base64",
                            "required": False,
                        },
                        "request_image_ref": {
                            "source": "payload.request_image_ref",
                            "required": False,
                        },
                    },
                    "result_mapping": {"result_binding": "http_response"},
                },
            )
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["submit_mode"] == "sync"
    assert payload["ack_policy"] == "ack-after-run-finished"
    assert payload["result_mode"] == "sync-reply"
    assert payload["input_binding_mapping"]["request_image_base64"]["required"] is False
    assert payload["input_binding_mapping"]["request_image_ref"]["required"] is False


def test_workflow_trigger_source_api_starts_enabled_zeromq_on_create(
    tmp_path: Path,
) -> None:
    """验证创建时启用 ZeroMQ TriggerSource 会同步启动 adapter。"""

    context = create_api_test_context(
        tmp_path,
        database_name="workflow-trigger-source-create-enabled.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    bind_endpoint = f"inproc://workflow-trigger-create-enabled-{uuid4().hex}"
    try:
        with context.client:
            _save_runtime(context.session_factory, observed_state="running")
            create_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "zeromq-trigger-source-create-enabled",
                    "project_id": "project-1",
                    "display_name": "ZeroMQ Trigger Create Enabled",
                    "trigger_kind": "zeromq-topic",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "enabled": True,
                    "transport_config": {
                        "bind_endpoint": bind_endpoint,
                        "default_input_binding": "request_image_ref",
                    },
                    "input_binding_mapping": {
                        "request_image_ref": {
                            "source": "payload.request_image_ref",
                            "required": False,
                        },
                    },
                    "result_mapping": {"result_binding": "http_response"},
                },
            )
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["enabled"] is True
    assert payload["desired_state"] == "running"
    assert payload["observed_state"] == "running"
    assert payload["health_summary"]["adapter_configured"] is True
    assert payload["health_summary"]["adapter_running"] is True


def test_workflow_trigger_source_api_controls_plc_register_adapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 TriggerSource 管理 API 可以启停第一阶段 PLC register adapter。"""

    class _IdleCoilClient:
        """测试用空闲 Modbus client。"""

        def __init__(self, host: str, *, port: int, timeout: float, retries: int) -> None:
            """记录连接参数。"""

            self.host = host
            self.port = port
            self.timeout = timeout
            self.retries = retries

        def close(self) -> None:
            """关闭测试 client。"""

        def read_coils(
            self,
            address: int,
            *,
            count: int,
            device_id: int,
        ) -> ModbusBitsReadResponse:
            """始终返回未命中的 coil 响应。"""

            return ModbusBitsReadResponse(
                bits=[False],
                address=address,
                count=count,
                dev_id=device_id,
                transaction_id=1,
                function_code=1,
                retries=0,
            )

    monkeypatch.setattr(
        "backend.service.infrastructure.integrations.modbus.plc_register_trigger_adapter.ProjectModbusTcpClient",
        _IdleCoilClient,
    )
    context = create_api_test_context(
        tmp_path,
        database_name="workflow-trigger-sources-plc-register.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with context.client:
            _save_runtime(context.session_factory, observed_state="running")
            create_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "plc-trigger-source-1",
                    "project_id": "project-1",
                    "display_name": "PLC Register Trigger",
                    "trigger_kind": "plc-register",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "transport_config": {
                        "driver": "modbus-tcp",
                        "host": "127.0.0.1",
                        "port": 502,
                        "unit_id": 1,
                        "register_address": "00001",
                        "data_type": "bool",
                        "poll_interval_ms": 50,
                        "reconnect_interval_ms": 50,
                    },
                    "match_rule": {
                        "operator": "eq",
                        "expected_value": True,
                        "trigger_mode": "enter-match",
                    },
                    "input_binding_mapping": {
                        "request_signal": {"source": "payload.observed_value"},
                    },
                    "result_mapping": {
                        "result_binding": "workflow_result",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            enable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/plc-trigger-source-1/enable",
                headers=headers,
            )
            health_response = context.client.get(
                "/api/v1/workflows/trigger-sources/plc-trigger-source-1/health",
                headers=headers,
            )
            disable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/plc-trigger-source-1/disable",
                headers=headers,
            )
            delete_response = context.client.delete(
                "/api/v1/workflows/trigger-sources/plc-trigger-source-1",
                headers=headers,
            )
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201

    assert enable_response.status_code == 200
    enable_payload = enable_response.json()
    assert enable_payload["enabled"] is True
    assert enable_payload["observed_state"] == "running"
    assert enable_payload["health_summary"]["adapter_configured"] is True
    assert enable_payload["health_summary"]["adapter_running"] is True

    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["observed_state"] == "running"
    assert health_payload["health_summary"]["adapter_running"] is True
    assert (
        health_payload["health_summary"]["supervisor"]["adapter_health"]["adapter_kind"]
        == "plc-register"
    )

    assert disable_response.status_code == 200
    disable_payload = disable_response.json()
    assert disable_payload["enabled"] is False
    assert disable_payload["desired_state"] == "stopped"
    assert disable_payload["health_summary"]["adapter_configured"] is True
    assert disable_payload["health_summary"]["adapter_running"] is False

    assert delete_response.status_code == 204


def test_workflow_trigger_source_api_controls_directory_poll_adapter(
    tmp_path: Path,
) -> None:
    """验证 TriggerSource 管理 API 可以启停 directory-poll adapter。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    context = create_api_test_context(
        tmp_path,
        database_name="workflow-trigger-sources-directory-poll.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with context.client:
            _save_runtime(context.session_factory, observed_state="running")
            create_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "directory-poll-trigger-1",
                    "project_id": "project-1",
                    "display_name": "Directory Poll Trigger",
                    "trigger_kind": "directory-poll",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "transport_config": {
                        "directory_path": str(incoming_dir),
                        "scan_interval_seconds": 0.1,
                        "batch_size": 1,
                        "min_stable_age_seconds": 0.0,
                        "extensions": ["png"],
                    },
                    "input_binding_mapping": {
                        "request_batch": {"source": "payload.files_value"},
                    },
                    "result_mapping": {
                        "result_binding": "workflow_result",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            enable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/directory-poll-trigger-1/enable",
                headers=headers,
            )
            health_response = context.client.get(
                "/api/v1/workflows/trigger-sources/directory-poll-trigger-1/health",
                headers=headers,
            )
            disable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/directory-poll-trigger-1/disable",
                headers=headers,
            )
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201

    assert enable_response.status_code == 200
    enable_payload = enable_response.json()
    assert enable_payload["enabled"] is True
    assert enable_payload["observed_state"] == "running"
    assert enable_payload["health_summary"]["adapter_configured"] is True
    assert enable_payload["health_summary"]["adapter_running"] is True

    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["observed_state"] == "running"
    assert health_payload["health_summary"]["adapter_running"] is True
    assert (
        health_payload["health_summary"]["supervisor"]["adapter_health"]["adapter_kind"]
        == "directory-poll"
    )

    assert disable_response.status_code == 200
    disable_payload = disable_response.json()
    assert disable_payload["enabled"] is False
    assert disable_payload["desired_state"] == "stopped"
    assert disable_payload["health_summary"]["adapter_running"] is False


def test_workflow_trigger_source_api_controls_directory_watch_adapter(
    tmp_path: Path,
) -> None:
    """验证 TriggerSource 管理 API 可以启停 directory-watch adapter。"""

    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    context = create_api_test_context(
        tmp_path,
        database_name="workflow-trigger-sources-directory-watch.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with context.client:
            _save_runtime(context.session_factory, observed_state="running")
            create_response = context.client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "directory-watch-trigger-1",
                    "project_id": "project-1",
                    "display_name": "Directory Watch Trigger",
                    "trigger_kind": "directory-watch",
                    "workflow_runtime_id": "workflow-runtime-1",
                    "submit_mode": "async",
                    "transport_config": {
                        "directory_path": str(incoming_dir),
                        "batch_size": 1,
                        "min_stable_age_seconds": 0.0,
                        "extensions": ["png"],
                        "force_polling": True,
                        "poll_delay_ms": 20,
                        "watch_timeout_ms": 100,
                    },
                    "input_binding_mapping": {
                        "request_batch": {"source": "payload.files_value"},
                    },
                    "result_mapping": {
                        "result_binding": "workflow_result",
                        "result_mode": "accepted-then-query",
                    },
                },
            )
            enable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/directory-watch-trigger-1/enable",
                headers=headers,
            )
            health_response = context.client.get(
                "/api/v1/workflows/trigger-sources/directory-watch-trigger-1/health",
                headers=headers,
            )
            disable_response = context.client.post(
                "/api/v1/workflows/trigger-sources/directory-watch-trigger-1/disable",
                headers=headers,
            )
    finally:
        context.session_factory.engine.dispose()

    assert create_response.status_code == 201

    assert enable_response.status_code == 200
    enable_payload = enable_response.json()
    assert enable_payload["enabled"] is True
    assert enable_payload["observed_state"] == "running"
    assert enable_payload["health_summary"]["adapter_configured"] is True
    assert enable_payload["health_summary"]["adapter_running"] is True

    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["observed_state"] == "running"
    assert health_payload["health_summary"]["adapter_running"] is True
    assert (
        health_payload["health_summary"]["supervisor"]["adapter_health"]["adapter_kind"]
        == "directory-watch"
    )

    assert disable_response.status_code == 200
    disable_payload = disable_response.json()
    assert disable_payload["enabled"] is False
    assert disable_payload["desired_state"] == "stopped"
    assert disable_payload["health_summary"]["adapter_running"] is False


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
