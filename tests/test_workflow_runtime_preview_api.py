"""实际 spawn Worker → 专用通道 → WebSocket 的预览验收。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
import pytest
from starlette.websockets import WebSocketDisconnect
from starlette.testclient import WebSocketDenialResponse

from backend.service.application.workflows.runtime.invokes import WorkflowRuntimeInvokeRequest
from backend.service.api.rest.v1.routes.workflow_runtime_support.services import build_workflow_runtime_service
from starlette.requests import Request
from tests.api_test_support import build_test_headers, build_valid_test_png_bytes
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client, _load_example_documents, _save_example_documents, _create_and_start_runtime,
    _build_image_base64_payload,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService


def test_runtime_preview_spawn_sync_async_none_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """观察链路独立于记录模式；覆盖同步、持久化/临时异步和失败。"""
    client, factory, storage = _create_runtime_api_client(
        tmp_path, database_name="runtime-preview.db", enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _save_example_documents(client=client, dataset_storage=storage, example_name="barcode_result_display")
            runtime_id = _create_and_start_runtime(client=client, headers=headers,
                application_id="barcode-result-display-app", display_name="Preview Test")
            base = f"/api/v1/workflows/app-runtimes/{runtime_id}"
            snapshot_response = client.get(f"{base}/preview-snapshot", headers=headers)
            assert snapshot_response.status_code == 200, snapshot_response.text
            snapshot = snapshot_response.json()
            assert snapshot["active"] is True
            assert snapshot["template"]["template_id"] == "barcode-result-display-template"
            assert snapshot["contract"]["format_id"] == "amvision.workflow-app-contract.v1"
            assert snapshot["app_mode"] is None
            referenced_node_type_ids = {
                node["node_type_id"] for node in snapshot["template"]["nodes"]
            }
            assert {
                definition["node_type_id"] for definition in snapshot["node_definitions"]
            } == referenced_node_type_ids
            assert snapshot["node_definition_warnings"] == []
            query = urlencode({key: snapshot[key] for key in (
                "workflow_runtime_id", "workflow_runtime_revision_id", "runtime_generation", "worker_instance_id",
            )})
            path = f"/ws/v1/workflows/app-runtimes/preview?{query}"
            denied_headers = {"Authorization": "Bearer invalid-runtime-preview-token"}
            assert client.get(f"{base}/preview-snapshot", headers=denied_headers).status_code == 401
            with pytest.raises(WebSocketDenialResponse) as denied:
                with client.websocket_connect(path, headers=denied_headers):
                    pass
            assert denied.value.status_code == 401
            stale_query = urlencode({
                "workflow_runtime_id": runtime_id,
                "workflow_runtime_revision_id": snapshot["workflow_runtime_revision_id"],
                "runtime_generation": snapshot["runtime_generation"] + 1,
                "worker_instance_id": snapshot["worker_instance_id"],
            })
            with pytest.raises(WebSocketDisconnect) as stale:
                with client.websocket_connect(f"/ws/v1/workflows/app-runtimes/preview?{stale_query}", headers=headers):
                    pass
            assert stale.value.code == 4409
            manager = client.app.state.workflow_runtime_worker_manager
            channel = manager.get_preview_channel(
                runtime_id,
                revision_id=snapshot["workflow_runtime_revision_id"],
                generation=snapshot["runtime_generation"],
                worker_instance_id=snapshot["worker_instance_id"],
            )
            from backend.service.application.workflows.runtime_preview import (
                RuntimePreviewCapacityError,
            )

            original_subscribe = channel.subscribe

            def reject_capacity():
                """模拟固定连接容量已经用尽。"""

                raise RuntimePreviewCapacityError(
                    "runtime_preview_capacity_exceeded"
                )

            monkeypatch.setattr(
                channel,
                "subscribe",
                reject_capacity,
            )
            try:
                with client.websocket_connect(path, headers=headers) as capacity_socket:
                    with pytest.raises(WebSocketDisconnect) as capacity:
                        capacity_socket.receive_json()
                assert capacity.value.code == 4429
            finally:
                monkeypatch.setattr(channel, "subscribe", original_subscribe)
            inputs = {"request_image_base64": _build_image_base64_payload(build_valid_test_png_bytes())}
            with client.websocket_connect(path, headers=headers) as ws:
                assert ws.receive_json()["state"] == "connected"
                assert channel.observed.is_set()
                prior_sequence = 0
                for mode in ("none", "minimal", "full"):
                    result = client.post(f"{base}/invoke?response_mode=run", headers=headers, json={
                        "input_bindings": inputs, "execution_metadata": {"workflow_run_record_mode": mode},
                    })
                    assert result.status_code == 200, result.text
                    assert result.json()["state"] == "succeeded", result.text
                    frame = ws.receive_json()
                    ws.send_text("ready")
                    assert frame["workflow_run_id"] == result.json()["workflow_run_id"]
                    assert frame["state"] == "succeeded"
                    assert frame["sequence"] > prior_sequence
                    prior_sequence = frame["sequence"]
                    types = {item["payload"]["type"] for item in frame["displays"]}
                    assert {"image-preview", "table-preview"} <= types
                    image = next(item for item in frame["displays"] if item["payload"]["type"] == "image-preview")
                    assert image["payload"]["image"]["image_base64"]
                    if mode == "none":
                        assert client.get(f"/api/v1/workflows/runs/{frame['workflow_run_id']}", headers=headers).status_code == 404
                async_result = client.post(f"{base}/runs", headers=headers, json={"input_bindings": inputs})
                assert async_result.status_code == 201, async_result.text
                assert ws.receive_json()["workflow_run_id"] == async_result.json()["workflow_run_id"]
                ws.send_text("ready")
                service = build_workflow_runtime_service(Request({"type": "http", "app": client.app}))
                transient = service.create_workflow_run(runtime_id, WorkflowRuntimeInvokeRequest(
                    input_bindings=inputs, execution_metadata={"workflow_run_record_mode": "none"},
                ), transient=True, created_by="preview-test")
                frame = ws.receive_json()
                ws.send_text("ready")
                assert frame["workflow_run_id"] == transient.workflow_run_id
                assert frame["state"] == "succeeded"
                failed = client.post(f"{base}/invoke?response_mode=run", headers=headers, json={"input_bindings": {}})
                assert failed.status_code == 200
                frame = ws.receive_json()
                assert frame["state"] == "failed"
                assert frame["displays"] == []
            assert not channel.observed.is_set()
            assert client.post(f"{base}/stop", headers=headers).status_code == 200
            assert not channel.thread.is_alive()
    finally:
        factory.engine.dispose()


def test_runtime_preview_snapshot_exposes_published_app_mode_and_contract(
    tmp_path: Path,
) -> None:
    """Runtime 快照返回同一发布版本的 App Mode 配置与公开输入契约。"""

    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="runtime-app-mode-snapshot.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            template, application = _load_example_documents("barcode_result_display")
            application = application.model_copy(
                update={
                    "metadata": {
                        **application.metadata,
                        "app_mode": {
                            "format_id": "amvision.workflow-app-mode.v1",
                            "title": "Barcode station",
                            "displays": [
                                {
                                    "node_id": "image_preview",
                                    "output_port": "body",
                                    "title": "Result image",
                                    "size": "large",
                                }
                            ],
                        },
                    }
                }
            )
            service = LocalWorkflowJsonService(
                dataset_storage=storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            service.save_template(project_id="project-1", template=template)
            service.save_application(project_id="project-1", application=application)
            create_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "application_id": application.application_id,
                    "display_name": "App Mode snapshot",
                },
            )
            assert create_response.status_code == 201, create_response.text
            runtime_id = create_response.json()["workflow_runtime_id"]

            snapshot_response = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/preview-snapshot",
                headers=headers,
            )

            assert snapshot_response.status_code == 200, snapshot_response.text
            snapshot = snapshot_response.json()
            assert snapshot["contract"]["application_id"] == application.application_id
            assert snapshot["contract"]["inputs"][0]["binding_id"] == "request_image_base64"
            assert snapshot["app_mode"] == {
                "format_id": "amvision.workflow-app-mode.v1",
                "title": "Barcode station",
                "displays": [
                    {
                        "node_id": "image_preview",
                        "output_port": "body",
                        "title": "Result image",
                        "size": "large",
                    }
                ],
            }
    finally:
        factory.engine.dispose()
