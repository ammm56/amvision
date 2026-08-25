"""Workflow App 版本化 TriggerSource 启动恢复专项测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backend.service.application.workflows.trigger_sources.trigger_source_service import (
    WorkflowTriggerSourceService,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
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


class _RecordingTriggerSourceSupervisor:
    """记录恢复启动且不创建真实协议监听的测试 supervisor。"""

    def __init__(self) -> None:
        self.adapters = {"http-api": object()}
        self.started_trigger_source_ids: list[str] = []
        self._managed_trigger_source_ids: set[str] = set()

    def supports_trigger_source(self, trigger_source: WorkflowTriggerSource) -> bool:
        """测试 supervisor 支持所有传入配置。"""

        return True

    def is_trigger_source_managed(self, trigger_source_id: str) -> bool:
        """返回 TriggerSource 是否已经启动。"""

        return trigger_source_id in self._managed_trigger_source_ids

    def start_trigger_source(self, trigger_source: WorkflowTriggerSource) -> None:
        """记录一次 adapter 启动。"""

        self.started_trigger_source_ids.append(trigger_source.trigger_source_id)
        self._managed_trigger_source_ids.add(trigger_source.trigger_source_id)

    def get_health(self, trigger_source_id: str) -> dict[str, object]:
        """返回可供服务持久化的最小健康摘要。"""

        return {
            "request_count": 0,
            "success_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "last_error": None,
            "adapter_health": {
                "running": trigger_source_id in self._managed_trigger_source_ids,
            },
        }


def test_versioned_trigger_recovery_uses_explicit_result_bindings(
    tmp_path: Path,
) -> None:
    """验证启动恢复兼容异步 Runtime 恢复窗口和历史结果映射语义。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-trigger-version-recovery.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    supervisor = _RecordingTriggerSourceSupervisor()
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
                release_notes="Trigger recovery contract",
            )
            create_runtime_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_id,
                },
            )
            assert create_runtime_response.status_code == 201
            runtime_id = create_runtime_response.json()["workflow_runtime_id"]
            _seed_transitional_runtime_and_legacy_triggers(
                session_factory=session_factory,
                runtime_id=runtime_id,
            )

            service = WorkflowTriggerSourceService(
                session_factory=session_factory,
                trigger_source_supervisor=supervisor,  # type: ignore[arg-type]
                dataset_storage=dataset_storage,
            )
            first_recovery = service.start_enabled_trigger_sources()
            sentinel_trigger = service.get_trigger_source("legacy-sentinel-trigger")
            unknown_trigger = service.get_trigger_source("unknown-output-trigger")
            accepted_trigger = service.get_trigger_source("accepted-query-trigger")

            # 再次启动恢复必须复用已管理 adapter，并保持 metadata 不变。
            sentinel_metadata = dict(sentinel_trigger.metadata)
            second_recovery = service.start_enabled_trigger_sources()
            sentinel_after_second_recovery = service.get_trigger_source(
                "legacy-sentinel-trigger"
            )

        assert first_recovery["started_count"] == 2
        assert first_recovery["failed_count"] == 1
        assert supervisor.started_trigger_source_ids == [
            "accepted-query-trigger",
            "legacy-sentinel-trigger",
        ]

        assert sentinel_trigger.observed_state == "running"
        assert sentinel_trigger.last_error is None
        assert sentinel_trigger.metadata[
            "validated_workflow_app_version_id"
        ] == version_id
        assert sentinel_trigger.metadata[
            "validated_workflow_runtime_generation"
        ] == 1
        assert isinstance(
            sentinel_trigger.metadata.get(
                "validated_workflow_runtime_revision_id"
            ),
            str,
        )
        assert isinstance(
            sentinel_trigger.metadata.get(
                "validated_workflow_contract_fingerprint"
            ),
            str,
        )

        assert accepted_trigger.observed_state == "running"
        assert unknown_trigger.observed_state == "failed"
        assert unknown_trigger.health_summary["recent_error"]["mapping_issues"] == [
            {
                "kind": "unknown_output_binding",
                "binding_id": "missing_contract_output",
            }
        ]

        assert second_recovery["started_count"] == 2
        assert second_recovery["failed_count"] == 1
        assert supervisor.started_trigger_source_ids == [
            "accepted-query-trigger",
            "legacy-sentinel-trigger",
        ]
        assert sentinel_after_second_recovery.metadata == sentinel_metadata
    finally:
        session_factory.engine.dispose()


def test_runtime_version_selection_uses_result_bindings_semantics(
    tmp_path: Path,
) -> None:
    """验证选版允许 fallback/未使用 binding，并拒绝真正未知的同步输出。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-trigger-version-selection.db",
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
            version_v1 = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="Result mapping v1",
            )
            allowed_runtime_id = _create_versioned_runtime(
                client=client,
                headers=headers,
                version_id=version_v1,
            )
            blocked_runtime_id = _create_versioned_runtime(
                client=client,
                headers=headers,
                version_id=version_v1,
            )
            _seed_version_selection_triggers(
                session_factory=session_factory,
                allowed_runtime_id=allowed_runtime_id,
                blocked_runtime_id=blocked_runtime_id,
            )

            LocalWorkflowJsonService(
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            ).save_application(
                project_id="project-1",
                application=application.model_copy(
                    update={"description": "result mapping compatible v2"}
                ),
            )
            version_v2 = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="Result mapping v2",
            )

            allowed_response = client.post(
                f"/api/v1/workflows/app-runtimes/{allowed_runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v2,
                    "expected_generation": 1,
                },
            )
            blocked_response = client.post(
                f"/api/v1/workflows/app-runtimes/{blocked_runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v2,
                    "expected_generation": 1,
                },
            )

        assert allowed_response.status_code == 200
        assert allowed_response.json()["revision_generation"] == 2
        assert blocked_response.status_code == 409
        assert blocked_response.json()["error"]["details"]["mapping_issues"] == [
                {
                    "trigger_source_id": "selection-unknown-output",
                    "missing_output_binding_ids": ["missing_contract_output"],
                }
        ]
    finally:
        session_factory.engine.dispose()


def _seed_transitional_runtime_and_legacy_triggers(
    *,
    session_factory: object,
    runtime_id: str,
) -> None:
    """构造 Runtime 异步恢复窗口和三类历史 TriggerSource。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(runtime_id)
        assert runtime is not None
        unit_of_work.workflow_runtime.replace_workflow_app_runtime_for_migration(
            replace(
                runtime,
                desired_state="running",
                observed_state="starting",
            )
        )
        common_fields = {
            "project_id": "project-1",
            "display_name": "Legacy trigger",
            "trigger_kind": "http-api",
            "workflow_runtime_id": runtime_id,
            "submit_mode": "sync",
            "enabled": True,
            "desired_state": "running",
            "observed_state": "failed",
            "input_binding_mapping": {
                "request_image_base64": {"source": "payload.image"}
            },
            "last_error": "previous startup raced runtime recovery",
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-01T00:00:00Z",
        }
        unit_of_work.workflow_trigger_sources.save_trigger_source(
            WorkflowTriggerSource(
                trigger_source_id="legacy-sentinel-trigger",
                result_mapping={"result_bindings": []},
                result_mode="sync-reply",
                **common_fields,
            )
        )
        unit_of_work.workflow_trigger_sources.save_trigger_source(
            WorkflowTriggerSource(
                trigger_source_id="unknown-output-trigger",
                result_mapping={"result_bindings": ["missing_contract_output"]},
                result_mode="sync-reply",
                **common_fields,
            )
        )
        unit_of_work.workflow_trigger_sources.save_trigger_source(
            WorkflowTriggerSource(
                trigger_source_id="accepted-query-trigger",
                result_mapping={"result_bindings": ["http_response"]},
                result_mode="accepted-then-query",
                **common_fields,
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _create_versioned_runtime(
    *,
    client: object,
    headers: dict[str, str],
    version_id: str,
) -> str:
    """创建一个保持 stopped 的版本化 Runtime。"""

    response = client.post(
        "/api/v1/workflows/app-runtimes",
        headers=headers,
        json={
            "project_id": "project-1",
            "workflow_app_version_id": version_id,
        },
    )
    assert response.status_code == 201
    return str(response.json()["workflow_runtime_id"])


def _seed_version_selection_triggers(
    *,
    session_factory: object,
    allowed_runtime_id: str,
    blocked_runtime_id: str,
) -> None:
    """保存选版测试使用的 fallback、未使用和非法结果映射。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        common_fields = {
            "project_id": "project-1",
            "display_name": "Version selection trigger",
            "trigger_kind": "http-api",
            "submit_mode": "sync",
            "enabled": False,
            "desired_state": "stopped",
            "observed_state": "stopped",
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-01T00:00:00Z",
        }
        for trigger_source in (
            WorkflowTriggerSource(
                trigger_source_id="selection-workflow-result",
                workflow_runtime_id=allowed_runtime_id,
                result_mapping={"result_bindings": []},
                result_mode="sync-reply",
                **common_fields,
            ),
            WorkflowTriggerSource(
                trigger_source_id="selection-accepted-query",
                workflow_runtime_id=allowed_runtime_id,
                result_mapping={"result_bindings": ["http_response"]},
                result_mode="accepted-then-query",
                **common_fields,
            ),
            WorkflowTriggerSource(
                trigger_source_id="selection-event-only",
                workflow_runtime_id=allowed_runtime_id,
                result_mapping={"result_bindings": []},
                result_mode="event-only",
                **common_fields,
            ),
            WorkflowTriggerSource(
                trigger_source_id="selection-unknown-output",
                workflow_runtime_id=blocked_runtime_id,
                result_mapping={"result_bindings": ["missing_contract_output"]},
                result_mode="sync-reply",
                **common_fields,
            ),
        ):
            unit_of_work.workflow_trigger_sources.save_trigger_source(trigger_source)
        unit_of_work.commit()
    finally:
        unit_of_work.close()
