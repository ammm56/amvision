"""真实发布与独立 worker 的三态、保存和恢复准入回归。"""

from pathlib import Path
from urllib.parse import urlencode

import pytest

from tests.api_test_support import build_test_headers
from tests.test_workflow_app_version_runtime import _publish_current_draft
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _save_example_documents,
    _wait_for_workflow_run,
)


def _create_runtime(client, headers, version_id):
    """只使用正式已发布版本创建运行时，不走草稿测试准入。"""
    response = client.post(
        "/api/v1/workflows/app-runtimes",
        headers=headers,
        json={
            "project_id": "project-1",
            "workflow_app_version_id": version_id,
            "display_name": "Three-state acceptance",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["workflow_runtime_id"]


def _invoke_with_display(client, headers, runtime_url, mode, payload):
    """订阅真实显示通道，关联本次 run，拒绝把上次状态作为当前结果。"""
    snapshot_response = client.get(f"{runtime_url}/preview-snapshot", headers=headers)
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot = snapshot_response.json()
    query = urlencode(
        {
            key: snapshot[key]
            for key in (
                "workflow_runtime_id",
                "workflow_runtime_revision_id",
                "runtime_generation",
                "worker_instance_id",
            )
        }
    )
    channel = client.app.state.workflow_runtime_worker_manager.get_preview_channel(
        snapshot["workflow_runtime_id"],
        revision_id=snapshot["workflow_runtime_revision_id"],
        generation=snapshot["runtime_generation"],
        worker_instance_id=snapshot["worker_instance_id"],
    )
    with client.websocket_connect(
        "/ws/v1/workflows/app-runtimes/preview?" + query, headers=headers
    ) as ws:
        assert ws.receive_json()["state"] == "connected"
        response = client.post(
            f"{runtime_url}/{'invoke' if mode == 'sync' else 'runs'}",
            headers=headers,
            params={"response_mode": "run"},
            json=payload,
        )
        assert response.status_code == (200 if mode == "sync" else 201), response.text
        run_id = response.json()["workflow_run_id"]
        run = _wait_for_workflow_run(
            client=client, headers=headers, workflow_run_id=run_id
        )
        assert run["state"] == "succeeded", run
        for _ in range(3):
            frame = ws.receive_json()
            ws.send_text("ready")
            if frame.get("workflow_run_id") == run_id:
                assert frame["state"] == "succeeded", frame
                assert frame["displays"][0]["payload"] == run["outputs"]["display"]
                # 先完成真实断开握手，再退出 TestClient 的强制取消作用域。
                ws.close()
                assert ws.receive()["type"] == "websocket.close"
                assert not channel.observed.is_set()
                assert not channel.subscriptions
                return response, run
        raise AssertionError("显示通道没有交付本次三态结果")


def test_published_decisions_preserve_all_states_after_stop_and_restart(tmp_path: Path):
    """六次真实调用覆盖同步/异步、重启、数据库保存和表格证据。"""
    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="inspection.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _template, application = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="inspection_limits",
            )
            version_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="Three-state acceptance",
            )
            runtime_id = _create_runtime(client, headers, version_id)
            runtime_url = f"/api/v1/workflows/app-runtimes/{runtime_id}"
            for mode in ("sync", "async"):
                start = client.post(f"{runtime_url}/start", headers=headers)
                assert start.status_code == 200, start.text
                try:
                    for state, value, reason in (
                        ("ok", 1.000000001, None),
                        ("ng", 1.25, None),
                        ("invalid", None, "missing_surface"),
                    ):
                        payload = {
                            "input_bindings": {
                                "measurements": {
                                    "observation_id": f"{mode}-{state}",
                                    "items": [
                                        {
                                            "item_id": "d",
                                            "unit": "mm",
                                            "value": value,
                                            "valid": value is not None,
                                            "reason": reason,
                                        }
                                    ],
                                }
                            }
                        }
                        response, run = _invoke_with_display(
                            client, headers, runtime_url, mode, payload
                        )
                        assert run["state"] == "succeeded", run
                        record = run["outputs"]["inspection"]
                        assert record["format_id"] == "amvision.result-record.v1"
                        assert record["state"] == state
                        assert record["passed"] is (state == "ok")
                        item = record["conditions"]["items"][0]
                        assert item["value"] == value
                        assert item["state"] == state
                        if state == "invalid":
                            assert item["reason"] == "missing_surface"
                            assert record["reason"] == "required_invalid"
                        display = run["outputs"]["display"]
                        assert display["rows"][0] == item
                        assert (
                            next(
                                col
                                for col in display["columns"]
                                if col["key"] == "state"
                            )["format"]
                            == "decision-state"
                        )
                        if mode == "sync":
                            assert response.json()["outputs"] == run["outputs"]
                finally:
                    stopped = client.post(f"{runtime_url}/stop", headers=headers)
                    assert stopped.status_code == 200, stopped.text
    finally:
        factory.engine.dispose()


def test_changed_decision_definition_blocks_old_publish_start_and_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """以旧身份正式发布；新实现拒绝启动/切回，但保留历史并允许审核重发。"""
    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="inspection-upgrade.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            registry = client.app.state.node_catalog_registry
            current = registry.get_workflow_node_definitions()
            old = tuple(
                item.model_copy(update={"version": "0.1.8", "metadata": {}})
                if item.node_type_id == "core.rule.check-limits"
                else item
                for item in current
            )
            _template, application = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="inspection_limits",
            )
            with monkeypatch.context() as historical:
                historical.setattr(
                    registry, "get_workflow_node_definitions", lambda: old
                )
                old_id = _publish_current_draft(
                    client=client,
                    headers=headers,
                    application_id=application.application_id,
                    release_notes="Historical definition identity",
                )
                runtime_id = _create_runtime(client, headers, old_id)
            url = f"/api/v1/workflows/app-runtimes/{runtime_id}"
            blocked = client.post(f"{url}/start", headers=headers)
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["error"]["details"]["requires_republish"] is True
            stopped = client.post(f"{url}/stop", headers=headers)
            assert stopped.status_code == 200, stopped.text
            history = client.get(
                f"/api/v1/workflows/projects/project-1/applications/{application.application_id}/versions/{old_id}",
                headers=headers,
            )
            assert history.status_code == 200, history.text
            new_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="Reviewed current decision semantics",
            )
            select = client.post(
                f"{url}/select-version",
                headers=headers,
                json={"workflow_app_version_id": new_id, "expected_generation": 1},
            )
            assert select.status_code == 200, select.text
            rejected = client.post(
                f"{url}/select-version",
                headers=headers,
                json={"workflow_app_version_id": old_id, "expected_generation": 2},
            )
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["error"]["details"]["requires_republish"] is True
            start = client.post(f"{url}/start", headers=headers)
            assert start.status_code == 200, start.text
            stop = client.post(f"{url}/stop", headers=headers)
            assert stop.status_code == 200, stop.text
    finally:
        factory.engine.dispose()
