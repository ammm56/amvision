"""WorkflowAppRuntime 配置更新与 WorkflowRun 分页列表 API 测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import build_test_headers
from tests.test_workflow_app_version_runtime import _publish_current_draft
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _save_example_documents,
)


def test_patch_runtime_config_requires_stopped_generation_and_disabled_triggers(
    tmp_path: Path,
) -> None:
    """验证停机更新运行配置时的 CAS 并发保护、运行中阻止与启用触发器阻止。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runtime-config-patch.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            version_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="v1",
            )
            create_resp = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_id,
                    "display_name": "Initial Runtime",
                    "request_timeout_seconds": 30,
                },
            )
            assert create_resp.status_code == 201
            runtime = create_resp.json()
            runtime_id = runtime["workflow_runtime_id"]
            assert runtime["revision_generation"] == 1

            # 1. generation 不匹配 -> 409 Conflict
            mismatch_resp = client.patch(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
                json={
                    "expected_generation": 99,
                    "display_name": "Wrong Generation",
                },
            )
            assert mismatch_resp.status_code == 409

            # 2. 正常停机修改 -> 200 OK 且 generation 递增
            patch_resp = client.patch(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
                json={
                    "expected_generation": 1,
                    "display_name": "Line A Station 1",
                    "request_timeout_seconds": 45,
                    "workflow_run_record_mode": "full",
                    "return_diagnostics": True,
                },
            )
            assert patch_resp.status_code == 200
            updated = patch_resp.json()
            assert updated["display_name"] == "Line A Station 1"
            assert updated["request_timeout_seconds"] == 45
            assert updated["revision_generation"] == 2
            exec_meta = updated["metadata"]["default_execution_metadata"]
            assert exec_meta["workflow_run_record_mode"] == "full"
            assert exec_meta["return_timing_metadata_enabled"] is True
            assert exec_meta["return_node_timings_enabled"] is True

            # 3. 绑定启用 TriggerSource 时禁止修改配置 -> 409 Conflict
            uow = SqlAlchemyUnitOfWork(session_factory.create_session())
            try:
                uow.workflow_trigger_sources.save_trigger_source(
                    WorkflowTriggerSource(
                        trigger_source_id="trigger-enabled-1",
                        project_id="project-1",
                        display_name="Enabled Trigger",
                        trigger_kind="http-api",
                        workflow_runtime_id=runtime_id,
                        enabled=True,
                        desired_state="stopped",
                        observed_state="stopped",
                        input_binding_mapping={},
                        result_mapping={},
                        created_at="2026-11-27T00:00:00Z",
                        updated_at="2026-11-27T00:00:00Z",
                    )
                )
                uow.commit()
            finally:
                uow.close()
            trigger_blocked_resp = client.patch(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
                json={"expected_generation": 2, "display_name": "Blocked By Trigger"},
            )
            assert trigger_blocked_resp.status_code == 409

            # 清理触发器后启动实例，运行中同样返回 409 Conflict
            uow = SqlAlchemyUnitOfWork(session_factory.create_session())
            try:
                src = uow.workflow_trigger_sources.get_trigger_source("trigger-enabled-1")
                assert src is not None
                uow.workflow_trigger_sources.save_trigger_source(
                    replace(src, enabled=False)
                )
                uow.commit()
            finally:
                uow.close()
            start_resp = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                headers=headers,
            )
            assert start_resp.status_code == 200
            running_blocked_resp = client.patch(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
                json={"expected_generation": 2, "display_name": "Blocked Running"},
            )
            assert running_blocked_resp.status_code == 409
            client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                headers=headers,
            )
    finally:
        client.close()


def test_list_workflow_runs_supports_filters_and_pagination(tmp_path: Path) -> None:
    """验证 /workflows/runs 支持按 runtime/application/state 过滤与分页头。"""

    client, _, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-runs-list.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            version_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="v1",
            )
            create_resp = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_id,
                    "display_name": "Runs List Runtime",
                    "metadata": {
                        "default_execution_metadata": {
                            "workflow_run_record_mode": "minimal",
                        }
                    },
                },
            )
            assert create_resp.status_code == 201
            runtime_id = create_resp.json()["workflow_runtime_id"]

            list_empty = client.get(
                "/api/v1/workflows/runs",
                headers=headers,
                params={"project_id": "project-1", "workflow_runtime_id": runtime_id},
            )
            assert list_empty.status_code == 200
            assert list_empty.json() == []
            assert list_empty.headers.get("X-Total-Count") == "0"
    finally:
        client.close()
