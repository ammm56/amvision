"""Workflow App 版本、Runtime revision 与迁移链路专项测试。"""

from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
from pathlib import PurePosixPath

from fastapi.testclient import TestClient

from backend.service.application.workflows.app_version_migration import (
    WorkflowAppVersionMigrationService,
)
from backend.service.application.workflows.app_version_service import (
    WorkflowAppVersionService,
    compute_workflow_app_content_fingerprint,
    compute_workflow_app_content_fingerprint_from_artifacts,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowRun,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.api_test_support import build_test_headers
from tests.test_workflow_barcode_nodes import _build_mixed_barcode_test_png_bytes
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _load_example_documents,
    _save_example_documents,
    _wait_for_workflow_run,
)


def test_runtime_switches_versions_with_stable_ids_cas_rollback_and_run_provenance(
    tmp_path: Path,
) -> None:
    """验证成功升级和回滚只推进 generation，不改变 Runtime/Trigger id。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-runtime.db",
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
                release_notes="v1 baseline",
            )
            create_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_v1,
                    "display_name": "Stable Barcode Runtime",
                },
            )
            assert create_response.status_code == 201
            runtime_id = create_response.json()["workflow_runtime_id"]
            assert create_response.json()["revision_generation"] == 1
            assert create_response.json()["active_revision_id"] is None
            staged_migration_result = WorkflowAppVersionMigrationService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            ).migrate()
            assert staged_migration_result.migrated_runtimes == 0
            assert staged_migration_result.skipped_runtimes == 1
            _set_runtime_state(
                session_factory=session_factory,
                runtime_id=runtime_id,
                desired_state="running",
                observed_state="starting",
            )
            normalized_count = WorkflowAppVersionMigrationService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            ).normalize_interrupted_staged_starts()
            interrupted_runtime = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
            ).json()
            assert normalized_count == 1
            assert interrupted_runtime["desired_state"] == "stopped"
            assert interrupted_runtime["observed_state"] == "failed"
            assert interrupted_runtime["active_revision_id"] is None

            start_v1 = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                headers=headers,
            )
            assert start_v1.status_code == 200
            active_v1_revision = start_v1.json()["active_revision_id"]
            worker_v1 = start_v1.json()["worker_instance_id"]
            assert isinstance(worker_v1, str) and worker_v1
            run_v1 = _invoke_barcode_runtime(
                client=client,
                headers=headers,
                runtime_id=runtime_id,
            )
            assert run_v1["workflow_app_version_id"] == version_v1
            assert run_v1["workflow_runtime_revision_id"] == active_v1_revision
            assert run_v1["runtime_generation"] == 1
            assert run_v1["snapshot_fingerprint"].startswith("sha256:")
            assert run_v1["worker_instance_id"] == worker_v1

            async_run_response = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/runs",
                headers=headers,
                json={
                    "input_bindings": {
                        "request_image_base64": {
                            "image_base64": base64.b64encode(
                                _build_mixed_barcode_test_png_bytes()
                            ).decode("ascii"),
                            "media_type": "image/png",
                        }
                    }
                },
            )
            assert async_run_response.status_code == 201
            async_run_v1 = _wait_for_workflow_run(
                client=client,
                headers=headers,
                workflow_run_id=async_run_response.json()["workflow_run_id"],
            )
            assert async_run_v1["state"] == "succeeded"
            assert async_run_v1["workflow_runtime_revision_id"] == active_v1_revision
            assert async_run_v1["workflow_app_version_id"] == version_v1
            assert async_run_v1["runtime_generation"] == 1
            assert (
                async_run_v1["snapshot_fingerprint"] == run_v1["snapshot_fingerprint"]
            )
            assert async_run_v1["worker_instance_id"] == worker_v1
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                    headers=headers,
                ).status_code
                == 200
            )

            trigger_id = "stable-http-trigger"
            trigger_response = client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": trigger_id,
                    "project_id": "project-1",
                    "display_name": "Stable HTTP Trigger",
                    "trigger_kind": "http-api",
                    "workflow_runtime_id": runtime_id,
                    "submit_mode": "sync",
                    "input_binding_mapping": {
                        "request_image_base64": {"source": "payload.image"}
                    },
                    "result_mapping": {"result_bindings": ["http_response"]},
                },
            )
            assert trigger_response.status_code == 201
            trigger_payload = trigger_response.json()
            assert (
                trigger_payload["metadata"]["validated_workflow_runtime_revision_id"]
                == active_v1_revision
            )
            assert (
                trigger_payload["metadata"]["validated_workflow_app_version_id"]
                == version_v1
            )
            assert (
                trigger_payload["metadata"]["validated_workflow_runtime_generation"]
                == 1
            )
            invalid_trigger_response = client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "invalid-contract-trigger",
                    "project_id": "project-1",
                    "display_name": "Invalid Contract Trigger",
                    "trigger_kind": "http-api",
                    "workflow_runtime_id": runtime_id,
                    "submit_mode": "sync",
                    "input_binding_mapping": {
                        "request_image_base64": {"source": "payload.image"},
                        "removed_input": {"source": "payload.removed"},
                    },
                    "result_mapping": {"result_bindings": ["http_response"]},
                },
            )
            assert invalid_trigger_response.status_code == 400
            assert invalid_trigger_response.json()["error"]["details"][
                "mapping_issues"
            ] == [
                {
                    "kind": "unknown_input_binding",
                    "binding_id": "removed_input",
                }
            ]

            workflow_service = LocalWorkflowJsonService(
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            workflow_service.save_application(
                project_id="project-1",
                application=application.model_copy(
                    update={"description": "compatible v2 internal change"}
                ),
            )
            version_v2 = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="v2 compatible",
            )
            stale_unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
            try:
                stale_runtime = (
                    stale_unit_of_work.workflow_runtime.get_workflow_app_runtime(
                        runtime_id
                    )
                )
            finally:
                stale_unit_of_work.close()
            assert stale_runtime is not None
            select_v2 = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v2,
                    "expected_generation": 1,
                },
            )
            stale_select = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v1,
                    "expected_generation": 1,
                },
            )
            assert select_v2.status_code == 200
            assert select_v2.json()["workflow_runtime_id"] == runtime_id
            assert select_v2.json()["revision_generation"] == 2
            assert stale_select.status_code == 409

            stale_state_unit_of_work = SqlAlchemyUnitOfWork(
                session_factory.create_session()
            )
            try:
                stale_state_updated = stale_state_unit_of_work.workflow_runtime.update_workflow_app_runtime_state_if_current(
                    replace(
                        stale_runtime,
                        observed_state="failed",
                        last_error="late generation-1 health event",
                    ),
                    expected_generation=stale_runtime.revision_generation,
                    expected_revision_id=str(stale_runtime.desired_revision_id),
                    expected_worker_instance_id=stale_runtime.worker_instance_id,
                )
                stale_state_unit_of_work.commit()
                runtime_after_late_state = (
                    stale_state_unit_of_work.workflow_runtime.get_workflow_app_runtime(
                        runtime_id
                    )
                )
            finally:
                stale_state_unit_of_work.close()
            assert stale_state_updated is False
            assert runtime_after_late_state is not None
            assert runtime_after_late_state.revision_generation == 2
            assert runtime_after_late_state.observed_state == "stopped"

            start_v2 = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                headers=headers,
            )
            assert start_v2.status_code == 200
            active_v2_revision = start_v2.json()["active_revision_id"]
            worker_v2 = start_v2.json()["worker_instance_id"]
            assert isinstance(worker_v2, str) and worker_v2 != worker_v1
            run_v2 = _invoke_barcode_runtime(
                client=client,
                headers=headers,
                runtime_id=runtime_id,
            )
            assert run_v2["workflow_app_version_id"] == version_v2
            assert run_v2["workflow_runtime_revision_id"] == active_v2_revision
            assert run_v2["runtime_generation"] == 2
            assert run_v2["snapshot_fingerprint"].startswith("sha256:")
            assert run_v2["worker_instance_id"] == worker_v2
            persisted_run_v1 = client.get(
                f"/api/v1/workflows/runs/{run_v1['workflow_run_id']}",
                headers=headers,
                params={"response_mode": "run"},
            )
            assert persisted_run_v1.status_code == 200
            assert persisted_run_v1.json()["worker_instance_id"] == worker_v1
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                    headers=headers,
                ).status_code
                == 200
            )

            rollback_select = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v1,
                    "expected_generation": 2,
                },
            )
            assert rollback_select.status_code == 200
            assert rollback_select.json()["revision_generation"] == 3
            rollback_start = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                headers=headers,
            )
            assert rollback_start.status_code == 200
            assert rollback_start.json()["workflow_runtime_id"] == runtime_id
            assert rollback_start.json()["revision_generation"] == 3

            revisions_response = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions",
                headers=headers,
            )
            revisions = revisions_response.json()
            revisions_page_response = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions",
                headers=headers,
                params={"offset": 1, "limit": 1},
            )
            detail_response = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions/"
                f"{revisions[0]['workflow_runtime_revision_id']}",
                headers=headers,
            )
            trigger_after = client.get(
                f"/api/v1/workflows/trigger-sources/{trigger_id}",
                headers=headers,
            )
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                    headers=headers,
                ).status_code
                == 200
            )

        assert revisions_response.status_code == 200
        assert [item["generation"] for item in revisions] == [3, 2, 1]
        assert [item["state"] for item in revisions] == ["active", "retired", "retired"]
        assert revisions[0]["workflow_app_version_id"] == version_v1
        assert revisions[1]["workflow_app_version_id"] == version_v2
        assert revisions_page_response.status_code == 200
        assert [item["generation"] for item in revisions_page_response.json()] == [2]
        assert revisions_page_response.headers["x-total-count"] == "3"
        assert revisions_page_response.headers["x-has-more"] == "true"
        assert revisions_page_response.headers["x-next-offset"] == "2"
        assert detail_response.status_code == 200
        assert detail_response.json() == revisions[0]
        assert trigger_after.status_code == 200
        assert trigger_after.json()["trigger_source_id"] == trigger_id
        assert trigger_after.json()["workflow_runtime_id"] == runtime_id
    finally:
        session_factory.engine.dispose()


def test_content_fingerprint_detects_node_definition_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证新发布会感知节点变更，冻结版本指纹不受当前 Catalog 影响。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-dependency-fingerprint.db",
        enable_local_buffer_broker=False,
    )
    try:
        with client:
            template, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            version_service = WorkflowAppVersionService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            snapshot = version_service.get_draft_snapshot(
                project_id="project-1",
                application_id=application.application_id,
            )
            current_fingerprint = compute_workflow_app_content_fingerprint(
                application=snapshot.application,
                template=template,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            frozen_fingerprint = (
                compute_workflow_app_content_fingerprint_from_artifacts(
                    application=snapshot.application.model_dump(mode="json"),
                    template=template.model_dump(mode="json"),
                    contract=snapshot.contract,
                    dependencies=snapshot.dependencies,
                )
            )
            definitions = list(
                client.app.state.node_catalog_registry.get_workflow_node_definitions()
            )
            referenced_type_id = template.nodes[0].node_type_id
            referenced_index = next(
                index
                for index, definition in enumerate(definitions)
                if definition.node_type_id == referenced_type_id
            )
            definitions[referenced_index] = definitions[referenced_index].model_copy(
                update={"version": "999.0.0"}
            )
            monkeypatch.setattr(
                client.app.state.node_catalog_registry,
                "get_workflow_node_definitions",
                lambda: tuple(definitions),
            )
            drifted_fingerprint = compute_workflow_app_content_fingerprint(
                application=snapshot.application,
                template=template,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            frozen_fingerprint_after_catalog_drift = (
                compute_workflow_app_content_fingerprint_from_artifacts(
                    application=snapshot.application.model_dump(mode="json"),
                    template=template.model_dump(mode="json"),
                    contract=snapshot.contract,
                    dependencies=snapshot.dependencies,
                )
            )

        assert current_fingerprint == snapshot.content_fingerprint
        assert frozen_fingerprint == current_fingerprint
        assert drifted_fingerprint != current_fingerprint
        assert frozen_fingerprint_after_catalog_drift == frozen_fingerprint
    finally:
        session_factory.engine.dispose()


def test_start_failure_keeps_last_active_revision(tmp_path: Path) -> None:
    """验证目标版本资产损坏时不会覆盖最后成功 active revision。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-start-failure.db",
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
                release_notes="valid v1",
            )
            create_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_v1,
                },
            )
            runtime_id = create_response.json()["workflow_runtime_id"]
            start_v1 = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                headers=headers,
            )
            active_v1_revision = start_v1.json()["active_revision_id"]
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                    headers=headers,
                ).status_code
                == 200
            )

            workflow_service = LocalWorkflowJsonService(
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            workflow_service.save_application(
                project_id="project-1",
                application=application.model_copy(
                    update={"description": "target v2 to corrupt after selection"}
                ),
            )
            version_v2 = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="target v2",
            )
            select_v2 = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v2,
                    "expected_generation": 1,
                },
            )
            assert select_v2.status_code == 200
            target_revision = select_v2.json()["desired_revision_id"]
            version_detail = client.get(
                f"/api/v1/workflows/projects/project-1/applications/"
                f"{application.application_id}/versions/{version_v2}",
                headers=headers,
            ).json()
            dataset_storage.write_json(
                version_detail["template_snapshot_object_key"],
                {"corrupted": True},
            )
            failed_start = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                headers=headers,
            )
            runtime_after = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
            ).json()
            revisions = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions",
                headers=headers,
            ).json()

        assert failed_start.status_code >= 400
        assert runtime_after["active_revision_id"] == active_v1_revision
        assert runtime_after["desired_revision_id"] == target_revision
        assert runtime_after["revision_generation"] == 2
        assert runtime_after["desired_state"] == "stopped"
        assert runtime_after["observed_state"] == "failed"
        revision_by_id = {
            item["workflow_runtime_revision_id"]: item for item in revisions
        }
        assert revision_by_id[active_v1_revision]["state"] == "active"
        assert revision_by_id[target_revision]["state"] == "failed"
    finally:
        session_factory.engine.dispose()


def test_breaking_contract_requires_override_and_never_breaks_trigger_mapping(
    tmp_path: Path,
) -> None:
    """验证破坏性契约需要显式确认，且确认也不能绕过 Trigger 映射校验。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-breaking-contract.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            template, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            version_v1 = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="contract v1",
            )
            create_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_v1,
                },
            )
            assert create_response.status_code == 201
            runtime_id = create_response.json()["workflow_runtime_id"]
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                    headers=headers,
                ).status_code
                == 200
            )
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                    headers=headers,
                ).status_code
                == 200
            )

            trigger_response = client.post(
                "/api/v1/workflows/trigger-sources",
                headers=headers,
                json={
                    "trigger_source_id": "contract-stable-trigger",
                    "project_id": "project-1",
                    "display_name": "Contract Stable Trigger",
                    "trigger_kind": "http-api",
                    "workflow_runtime_id": runtime_id,
                    "submit_mode": "sync",
                    "input_binding_mapping": {
                        "request_image_base64": {"source": "payload.image"}
                    },
                    "result_mapping": {"result_bindings": ["http_response"]},
                },
            )
            assert trigger_response.status_code == 201

            workflow_service = LocalWorkflowJsonService(
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            workflow_service.save_template(
                project_id="project-1",
                template=template.model_copy(update={"template_outputs": ()}),
            )
            breaking_application = application.model_copy(
                update={
                    "bindings": tuple(
                        binding
                        for binding in application.bindings
                        if binding.binding_id != "http_response"
                    )
                }
            )
            workflow_service.save_application(
                project_id="project-1",
                application=breaking_application,
            )
            version_v2 = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=application.application_id,
                release_notes="remove public output",
            )
            comparison_response = client.get(
                f"/api/v1/workflows/projects/project-1/applications/"
                f"{application.application_id}/versions/{version_v1}/compare",
                headers=headers,
            )
            blocked_response = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v2,
                    "expected_generation": 1,
                },
            )
            mapping_blocked_response = client.post(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/select-version",
                headers=headers,
                json={
                    "workflow_app_version_id": version_v2,
                    "expected_generation": 1,
                    "allow_breaking_contract": True,
                    "breaking_change_reason": "已安排第三方契约升级",
                },
            )
            runtime_response = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
            )

        assert comparison_response.status_code == 200
        comparison = comparison_response.json()
        assert comparison["compatible"] is False
        assert {
            "kind": "removed",
            "direction": "outputs",
            "binding_id": "http_response",
        } in comparison["breaking_changes"]
        assert blocked_response.status_code == 409
        blocked_error = blocked_response.json()["error"]
        assert blocked_error["code"] == "resource_conflict"
        assert blocked_error["details"]["breaking_changes"]
        assert mapping_blocked_response.status_code == 409
        mapping_error = mapping_blocked_response.json()["error"]
        assert mapping_error["code"] == "resource_conflict"
        assert mapping_error["details"]["mapping_issues"] == [
                {
                    "trigger_source_id": "contract-stable-trigger",
                    "missing_output_binding_ids": ["http_response"],
                }
        ]
        assert runtime_response.status_code == 200
        assert runtime_response.json()["revision_generation"] == 1
        assert (
            runtime_response.json()["desired_revision_id"]
            == runtime_response.json()["active_revision_id"]
        )
    finally:
        session_factory.engine.dispose()


def test_startup_migrates_legacy_runtime_run_and_preserves_trigger_ids(
    tmp_path: Path,
) -> None:
    """验证启动迁移使用旧 Runtime 自身快照并保持全部稳定 id。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-legacy-migration.db",
        enable_local_buffer_broker=False,
    )
    runtime_id = "legacy-runtime-stable-id"
    never_started_runtime_id = "legacy-runtime-never-started"
    run_id = "legacy-run-stable-id"
    trigger_id = "legacy-trigger-stable-id"
    template, application = _load_example_documents("barcode_result_display")
    application = application.model_copy(
        update={"metadata": {**dict(application.metadata), "project_id": "project-1"}}
    )
    application_key = (
        f"workflows/runtime/app-runtimes/{runtime_id}/application.snapshot.json"
    )
    template_key = f"workflows/runtime/app-runtimes/{runtime_id}/template.snapshot.json"
    dataset_storage.write_json(application_key, application.model_dump(mode="json"))
    dataset_storage.write_json(template_key, template.model_dump(mode="json"))
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id=runtime_id,
                project_id="project-1",
                application_id=application.application_id,
                display_name="Legacy Stable Runtime",
                application_snapshot_object_key=application_key,
                template_snapshot_object_key=template_key,
                desired_state="stopped",
                observed_state="stopped",
                created_at="2026-08-01T00:00:00Z",
                updated_at="2026-08-01T00:00:00Z",
            )
        )
        unit_of_work.workflow_runtime.save_workflow_app_runtime(
            WorkflowAppRuntime(
                workflow_runtime_id=never_started_runtime_id,
                project_id="project-1",
                application_id=application.application_id,
                display_name="Legacy Never Started Runtime",
                application_snapshot_object_key=application_key,
                template_snapshot_object_key=template_key,
                desired_state="stopped",
                observed_state="stopped",
                created_at="2026-08-01T00:00:00Z",
                updated_at="2026-08-01T00:00:00Z",
            )
        )
        unit_of_work.workflow_runtime.save_workflow_run(
            WorkflowRun(
                workflow_run_id=run_id,
                workflow_runtime_id=runtime_id,
                project_id="project-1",
                application_id=application.application_id,
                state="succeeded",
                created_at="2026-08-01T00:01:00Z",
            )
        )
        unit_of_work.workflow_trigger_sources.save_trigger_source(
            WorkflowTriggerSource(
                trigger_source_id=trigger_id,
                project_id="project-1",
                display_name="Legacy Stable Trigger",
                trigger_kind="http-api",
                workflow_runtime_id=runtime_id,
                input_binding_mapping={
                    "request_image_base64": {"source": "payload.image"}
                },
                result_mapping={"result_bindings": ["http_response"]},
                created_at="2026-08-01T00:00:00Z",
                updated_at="2026-08-01T00:00:00Z",
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            runtime_response = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}",
                headers=headers,
            )
            revisions_response = client.get(
                f"/api/v1/workflows/app-runtimes/{runtime_id}/revisions",
                headers=headers,
            )
            never_started_runtime_response = client.get(
                f"/api/v1/workflows/app-runtimes/{never_started_runtime_id}",
                headers=headers,
            )
            never_started_revisions_response = client.get(
                f"/api/v1/workflows/app-runtimes/{never_started_runtime_id}/revisions",
                headers=headers,
            )
            run_response = client.get(
                f"/api/v1/workflows/runs/{run_id}",
                headers=headers,
                params={"response_mode": "run"},
            )
            trigger_response = client.get(
                f"/api/v1/workflows/trigger-sources/{trigger_id}",
                headers=headers,
            )
            # 再执行一次迁移，验证不会生成重复版本或 revision。
            second_result = WorkflowAppVersionMigrationService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            ).migrate()

        assert runtime_response.status_code == 200
        runtime_payload = runtime_response.json()
        assert runtime_payload["workflow_runtime_id"] == runtime_id
        assert runtime_payload["revision_generation"] == 1
        assert (
            runtime_payload["active_revision_id"]
            == runtime_payload["desired_revision_id"]
        )
        assert runtime_payload["metadata"]["legacy_runtime_snapshot_migrated"] is True
        assert revisions_response.status_code == 200
        assert len(revisions_response.json()) == 1
        revision = revisions_response.json()[0]
        assert revision["state"] == "active"
        assert run_response.status_code == 200
        assert (
            run_response.json()["workflow_runtime_revision_id"]
            == revision["workflow_runtime_revision_id"]
        )
        assert (
            run_response.json()["workflow_app_version_id"]
            == revision["workflow_app_version_id"]
        )
        assert run_response.json()["runtime_generation"] == 1
        assert run_response.json()["worker_instance_id"] is None
        assert trigger_response.status_code == 200
        assert trigger_response.json()["trigger_source_id"] == trigger_id
        assert trigger_response.json()["workflow_runtime_id"] == runtime_id
        assert never_started_runtime_response.status_code == 200
        never_started_runtime = never_started_runtime_response.json()
        assert never_started_runtime["revision_generation"] == 1
        assert never_started_runtime["active_revision_id"] is None
        assert never_started_runtime["desired_revision_id"] is not None
        assert never_started_revisions_response.status_code == 200
        never_started_revisions = never_started_revisions_response.json()
        assert len(never_started_revisions) == 1
        assert never_started_revisions[0]["state"] == "staged"
        assert never_started_revisions[0]["activated_at"] is None
        assert second_result.migrated_runtimes == 0
        assert second_result.skipped_runtimes == 2
    finally:
        session_factory.engine.dispose()


def test_incomplete_version_publish_recovers_complete_staging_and_fails_missing_assets(
    tmp_path: Path,
) -> None:
    """验证发布中断后只恢复完整 manifest，不完整资产确定进入 failed。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-publish-recovery.db",
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
                release_notes="publish recovery",
            )
            version_service = WorkflowAppVersionService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            version = version_service.get_version_by_id(
                project_id="project-1",
                workflow_app_version_id=version_id,
            )
            final_dir = str(
                PurePosixPath(version.application_snapshot_object_key).parent
            )
            staging_dir = (
                "workflows/projects/project-1/applications/"
                f"{application.application_id}/versions/.staging/{version_id}"
            )
            dataset_storage.move_tree(final_dir, staging_dir)
            _set_version_state(
                session_factory=session_factory,
                version_id=version_id,
                state="publishing",
            )

            recovered = version_service.recover_incomplete_versions()
            recovered_version = version_service.get_version_by_id(
                project_id="project-1",
                workflow_app_version_id=version_id,
            )
            assert recovered.recovered_versions == 1
            assert recovered.failed_versions == 0
            assert recovered_version.state == "published"
            assert dataset_storage.resolve(
                recovered_version.application_snapshot_object_key
            ).is_file()

            dataset_storage.delete_tree(final_dir)
            _set_version_state(
                session_factory=session_factory,
                version_id=version_id,
                state="publishing",
            )
            failed = version_service.recover_incomplete_versions()
            failed_version = version_service.get_version_by_id(
                project_id="project-1",
                workflow_app_version_id=version_id,
            )

        assert failed.recovered_versions == 0
        assert failed.failed_versions == 1
        assert failed_version.state == "failed"
        assert failed_version.error is not None
        assert "manifest" in failed_version.error
    finally:
        session_factory.engine.dispose()


def test_workflow_app_version_archive_restore_uses_state_cas_and_preserves_existing_runtime(
    tmp_path: Path,
) -> None:
    """验证归档不破坏既有 Runtime，而新选择必须先显式恢复版本。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-archive.db",
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
                release_notes="archive baseline",
            )
            create_response = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_id,
                    "display_name": "Archived Version Runtime",
                },
            )
            assert create_response.status_code == 201
            runtime_id = create_response.json()["workflow_runtime_id"]

            archive_response = client.post(
                (
                    "/api/v1/workflows/projects/project-1/applications/"
                    f"{application.application_id}/versions/{version_id}/archive"
                ),
                headers=headers,
                json={"expected_state": "published"},
            )
            assert archive_response.status_code == 200
            assert archive_response.json()["state"] == "archived"

            stale_archive = client.post(
                (
                    "/api/v1/workflows/projects/project-1/applications/"
                    f"{application.application_id}/versions/{version_id}/archive"
                ),
                headers=headers,
                json={"expected_state": "published"},
            )
            assert stale_archive.status_code == 409
            assert stale_archive.json()["error"]["details"]["current_state"] == (
                "archived"
            )

            blocked_create = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_id,
                    "display_name": "Blocked Archived Runtime",
                },
            )
            assert blocked_create.status_code == 409

            # 既有 revision 已经固定不可变快照，归档后仍可正常启动和停止。
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/start",
                    headers=headers,
                ).status_code
                == 200
            )
            assert (
                client.post(
                    f"/api/v1/workflows/app-runtimes/{runtime_id}/stop",
                    headers=headers,
                ).status_code
                == 200
            )

            restore_response = client.post(
                (
                    "/api/v1/workflows/projects/project-1/applications/"
                    f"{application.application_id}/versions/{version_id}/restore"
                ),
                headers=headers,
                json={"expected_state": "archived"},
            )
            assert restore_response.status_code == 200
            assert restore_response.json()["state"] == "published"

            stale_restore = client.post(
                (
                    "/api/v1/workflows/projects/project-1/applications/"
                    f"{application.application_id}/versions/{version_id}/restore"
                ),
                headers=headers,
                json={"expected_state": "archived"},
            )
            assert stale_restore.status_code == 409
            assert stale_restore.json()["error"]["details"]["current_state"] == (
                "published"
            )
    finally:
        session_factory.engine.dispose()


def _publish_current_draft(
    *,
    client: TestClient,
    headers: dict[str, str],
    application_id: str,
    release_notes: str,
) -> str:
    """发布当前草稿并返回版本 id。"""

    draft_response = client.get(
        f"/api/v1/workflows/projects/project-1/applications/{application_id}",
        headers=headers,
    )
    assert draft_response.status_code == 200
    publish_response = client.post(
        f"/api/v1/workflows/projects/project-1/applications/{application_id}/versions",
        headers=headers,
        json={
            "expected_draft_fingerprint": draft_response.json()["draft_fingerprint"],
            "release_notes": release_notes,
        },
    )
    assert publish_response.status_code == 201
    return str(publish_response.json()["workflow_app_version_id"])


def _invoke_barcode_runtime(
    *, client: TestClient, headers: dict[str, str], runtime_id: str
) -> dict[str, object]:
    """同步调用条码 Runtime 并返回完整 WorkflowRun。"""

    image_base64 = base64.b64encode(_build_mixed_barcode_test_png_bytes()).decode(
        "ascii"
    )
    response = client.post(
        f"/api/v1/workflows/app-runtimes/{runtime_id}/invoke",
        headers=headers,
        params={"response_mode": "run"},
        json={
            "input_bindings": {
                "request_image_base64": {
                    "image_base64": image_base64,
                    "media_type": "image/png",
                }
            }
        },
    )
    assert response.status_code == 200
    return response.json()


def _set_version_state(*, session_factory: object, version_id: str, state: str) -> None:
    """直接设置发布状态，构造进程中断恢复场景。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.workflow_runtime.update_workflow_app_version_state(
            version_id,
            state=state,
            completed_at=None,
            error=None,
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _set_runtime_state(
    *,
    session_factory: object,
    runtime_id: str,
    desired_state: str,
    observed_state: str,
) -> None:
    """直接设置 Runtime 状态，构造服务进程在 start 中断的场景。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(runtime_id)
        assert runtime is not None
        unit_of_work.workflow_runtime.replace_workflow_app_runtime_for_migration(
            replace(
                runtime,
                desired_state=desired_state,
                observed_state=observed_state,
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
