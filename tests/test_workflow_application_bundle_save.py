"""Workflow Application + Template bundle 保存专项测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest

from backend.service.application.errors import (
    ResourceConflictError,
    ResourceNotFoundError,
    WorkflowRecoveryRequiredError,
)
from backend.service.application.workflows.app_version_service import (
    WorkflowAppVersionService,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.application_bundle_journal import (
    WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT,
    WorkflowApplicationBundleJournalService,
)
from backend.service.application.workflows.documents.applications import (
    WorkflowApplicationDocumentStore,
)
from backend.service.application.workflows.documents.storage import (
    build_application_object_key,
    build_resource_summary_object_key,
    build_template_object_key,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    WORKFLOW_LIFECYCLE_RESERVED_PREFIX,
    build_workflow_template_lifecycle_resource_key,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from tests.test_workflows_api import (
    _build_application_payload,
    _build_template_payload,
    _build_workflow_write_headers,
    _create_test_client,
)


def test_bundle_save_blocks_publish_then_publishes_one_new_consistent_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 bundle 保存期间发布立即冲突，完成后只发布新组合。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    application_id = "inspection-api-app"
    endpoint = f"/api/v1/workflows/projects/project-1/applications/{application_id}"
    template_payload = _build_template_payload()
    application_payload = _build_application_payload()
    try:
        with client:
            original_save = client.put(
                endpoint,
                headers=_build_workflow_write_headers(),
                json={
                    "application": application_payload,
                    "template": template_payload,
                },
            )
            assert original_save.status_code == 201
            saved_template_payload = original_save.json()["saved_template"]["template"]
            assert (
                saved_template_payload["template_id"] == template_payload["template_id"]
            )
            assert (
                saved_template_payload["template_version"]
                == (template_payload["template_version"])
            )
            original_fingerprint = original_save.json()["draft_fingerprint"]
            shared_application = deepcopy(application_payload)
            shared_application["application_id"] = "shared-template-app"
            shared_application["display_name"] = "Shared Template App"
            shared_endpoint = (
                "/api/v1/workflows/projects/project-1/applications/shared-template-app"
            )
            shared_save = client.put(
                shared_endpoint,
                headers=_build_workflow_write_headers(),
                json={"application": shared_application},
            )
            assert shared_save.status_code == 201
            shared_fingerprint = shared_save.json()["draft_fingerprint"]

            next_template = deepcopy(template_payload)
            next_template["display_name"] = "Inspection Graph Bundle Updated"
            next_application = deepcopy(application_payload)
            next_application["display_name"] = "Inspection App Bundle Updated"
            entered_save = Event()
            release_save = Event()
            original_bundle_save = LocalWorkflowJsonService.save_application_bundle

            def pause_bundle_save(
                service: LocalWorkflowJsonService,
                **kwargs: object,
            ):
                entered_save.set()
                if not release_save.wait(timeout=10):
                    raise TimeoutError("bundle save test barrier timeout")
                return original_bundle_save(service, **kwargs)

            monkeypatch.setattr(
                LocalWorkflowJsonService,
                "save_application_bundle",
                pause_bundle_save,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    client.put,
                    endpoint,
                    headers=_build_workflow_write_headers(),
                    json={
                        "application": next_application,
                        "template": next_template,
                    },
                )
                assert entered_save.wait(timeout=10)
                version_service = WorkflowAppVersionService(
                    session_factory=session_factory,
                    dataset_storage=dataset_storage,
                    node_catalog_registry=client.app.state.node_catalog_registry,
                )
                with pytest.raises(ResourceConflictError):
                    version_service.publish_version(
                        project_id="project-1",
                        application_id="shared-template-app",
                        expected_draft_fingerprint=shared_fingerprint,
                        release_notes="must conflict while saving",
                        display_version=None,
                        created_by="test",
                    )
                release_save.set()
                saved = future.result(timeout=10)

            assert saved.status_code == 201
            next_fingerprint = saved.json()["draft_fingerprint"]
            assert next_fingerprint != original_fingerprint
            published = client.post(
                f"{endpoint}/versions",
                headers=_build_workflow_write_headers(),
                json={
                    "expected_draft_fingerprint": next_fingerprint,
                    "release_notes": "consistent bundle",
                },
            )
            assert published.status_code == 201
            detail = client.get(
                f"{endpoint}/versions/{published.json()['workflow_app_version_id']}",
                headers=_build_workflow_write_headers(),
            )
            assert detail.status_code == 200
            assert detail.json()["application"]["display_name"] == (
                "Inspection App Bundle Updated"
            )
            assert detail.json()["template"]["display_name"] == (
                "Inspection Graph Bundle Updated"
            )
    finally:
        session_factory.engine.dispose()


def test_bundle_second_step_failure_restores_original_four_authoritative_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Application 写入失败会恢复原 Template/Application 及 sidecar。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    application_id = "inspection-api-app"
    endpoint = f"/api/v1/workflows/projects/project-1/applications/{application_id}"
    template_payload = _build_template_payload()
    application_payload = _build_application_payload()
    template_object_key = build_template_object_key(
        project_id="project-1",
        template_id=template_payload["template_id"],
        template_version=template_payload["template_version"],
    )
    application_object_key = build_application_object_key(
        project_id="project-1",
        application_id=application_id,
    )
    authoritative_keys = (
        template_object_key,
        build_resource_summary_object_key(template_object_key),
        application_object_key,
        build_resource_summary_object_key(application_object_key),
    )
    try:
        with client:
            original = client.put(
                endpoint,
                headers=_build_workflow_write_headers(),
                json={
                    "application": application_payload,
                    "template": template_payload,
                },
            )
            assert original.status_code == 201
            original_bytes = {
                key: dataset_storage.resolve(key).read_bytes()
                for key in authoritative_keys
            }
            next_template = deepcopy(template_payload)
            next_template["display_name"] = "must rollback template"
            next_application = deepcopy(application_payload)
            next_application["display_name"] = "must rollback application"
            original_application_save = (
                WorkflowApplicationDocumentStore.save_application
            )

            def fail_second_step(
                _store: WorkflowApplicationDocumentStore,
                **_kwargs: object,
            ) -> None:
                raise OSError("injected Application write failure")

            monkeypatch.setattr(
                WorkflowApplicationDocumentStore,
                "save_application",
                fail_second_step,
            )
            with pytest.raises(OSError, match="injected Application write failure"):
                client.put(
                    endpoint,
                    headers=_build_workflow_write_headers(),
                    json={
                        "application": next_application,
                        "template": next_template,
                    },
                )
            assert {
                key: dataset_storage.resolve(key).read_bytes()
                for key in authoritative_keys
            } == original_bytes

            monkeypatch.setattr(
                WorkflowApplicationDocumentStore,
                "save_application",
                original_application_save,
            )
            retried = client.put(
                endpoint,
                headers=_build_workflow_write_headers(),
                json={
                    "application": next_application,
                    "template": next_template,
                },
            )
            assert retried.status_code == 201
            assert retried.json()["saved_template"]["template"]["display_name"] == (
                "must rollback template"
            )
    finally:
        session_factory.engine.dispose()


def test_reserved_template_claim_recovers_and_all_template_mutators_observe_it(
    tmp_path: Path,
) -> None:
    """验证保留 Template claim 不会成为 tombstone，且所有公开 mutator 共用它。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    template_payload = _build_template_payload()
    template_endpoint = (
        "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0"
    )
    template_resource_key = build_workflow_template_lifecycle_resource_key(
        template_id="inspection-demo",
        template_version="1.0.0",
    )
    lifecycle_service = WorkflowApplicationLifecycleService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    try:
        with client:
            saved = client.put(
                template_endpoint,
                headers=_build_workflow_write_headers(),
                json={"template": template_payload},
            )
            assert saved.status_code == 201
            interrupted = lifecycle_service.acquire(
                project_id="project-1",
                application_id=template_resource_key,
                operation="saving",
            )
            assert interrupted.deleted is False
            assert (
                client.put(
                    template_endpoint,
                    headers=_build_workflow_write_headers(),
                    json={"template": template_payload},
                ).status_code
                == 409
            )
            assert (
                client.delete(
                    template_endpoint,
                    headers=_build_workflow_write_headers(),
                ).status_code
                == 409
            )
            assert (
                client.post(
                    f"{template_endpoint}/copy",
                    headers=_build_workflow_write_headers(),
                    json={
                        "target_template_id": "inspection-copy",
                        "target_template_version": "1.0.0",
                    },
                ).status_code
                == 409
            )

            recovered = lifecycle_service.recover_interrupted_operations()
            assert recovered.recovered_operations == 1
            recovered_claim = lifecycle_service.get(
                project_id="project-1",
                application_id=template_resource_key,
            )
            assert recovered_claim.state == "idle"
            assert recovered_claim.deleted is False
            with pytest.raises(RuntimeError, match="injected resource failure"):
                with lifecycle_service.operation(
                    project_id="project-1",
                    application_id=template_resource_key,
                    operation="saving",
                ):
                    raise RuntimeError("injected resource failure")
            after_failure = lifecycle_service.get(
                project_id="project-1",
                application_id=template_resource_key,
            )
            assert after_failure.state == "idle"
            assert after_failure.deleted is False
            with lifecycle_service.operation(
                project_id="project-1",
                application_id=template_resource_key,
                operation="saving",
            ):
                pass
    finally:
        session_factory.engine.dispose()


@pytest.mark.parametrize("replaced_object_count", [1, 2, 3, 4])
def test_bundle_journal_recovers_every_interrupted_authoritative_write_stage(
    tmp_path: Path,
    replaced_object_count: int,
) -> None:
    """验证进程在任一权威 replace 后退出，启动恢复都还原完整旧草稿。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    application_id = "inspection-api-app"
    template_payload = _build_template_payload()
    application_payload = _build_application_payload()
    endpoint = f"/api/v1/workflows/projects/project-1/applications/{application_id}"
    template_object_key = build_template_object_key(
        project_id="project-1",
        template_id=str(template_payload["template_id"]),
        template_version=str(template_payload["template_version"]),
    )
    application_object_key = build_application_object_key(
        project_id="project-1",
        application_id=application_id,
    )
    authoritative_keys = (
        template_object_key,
        build_resource_summary_object_key(template_object_key),
        application_object_key,
        build_resource_summary_object_key(application_object_key),
    )
    try:
        with client:
            saved = client.put(
                endpoint,
                headers=_build_workflow_write_headers(),
                json={"application": application_payload, "template": template_payload},
            )
            assert saved.status_code == 201
            original_bytes = {
                key: dataset_storage.resolve(key).read_bytes()
                for key in authoritative_keys
            }
            journals = WorkflowApplicationBundleJournalService(
                dataset_storage=dataset_storage
            )
            operation_id = (
                f"workflow-application-operation-crash-{replaced_object_count}"
            )
            journal = journals.prepare(
                operation_id=operation_id,
                project_id="project-1",
                application_id=application_id,
                template_id=str(template_payload["template_id"]),
                template_version=str(template_payload["template_version"]),
            )
            assert journal.authoritative_object_keys == authoritative_keys
            for index, object_key in enumerate(
                authoritative_keys[:replaced_object_count]
            ):
                dataset_storage.write_bytes(
                    object_key,
                    f"interrupted-new-content-{index}".encode(),
                )

            recovered = journals.recover_interrupted_journals()

            assert recovered.scanned_journals == 1
            assert recovered.rolled_back_journals == 1
            assert {
                key: dataset_storage.resolve(key).read_bytes()
                for key in authoritative_keys
            } == original_bytes
            assert not dataset_storage.resolve(journal.journal_root_key).exists()
    finally:
        session_factory.engine.dispose()


def test_legacy_runtime_create_observes_shared_template_claim(
    tmp_path: Path,
) -> None:
    """验证旧 application_id Runtime 创建不会越过共享 Template 写 claim。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    template_payload = _build_template_payload()
    application_payload = _build_application_payload()
    endpoint = "/api/v1/workflows/projects/project-1/applications/inspection-api-app"
    lifecycle_service = WorkflowApplicationLifecycleService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    template_resource_key = build_workflow_template_lifecycle_resource_key(
        template_id=str(template_payload["template_id"]),
        template_version=str(template_payload["template_version"]),
    )
    try:
        with client:
            saved = client.put(
                endpoint,
                headers=_build_workflow_write_headers(),
                json={"application": application_payload, "template": template_payload},
            )
            assert saved.status_code == 201
            claim = lifecycle_service.acquire(
                project_id="project-1",
                application_id=template_resource_key,
                operation="saving",
            )
            created = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=_build_workflow_write_headers(),
                json={
                    "project_id": "project-1",
                    "application_id": "inspection-api-app",
                    "display_name": "must conflict",
                },
            )
            assert created.status_code == 409
            versions = client.get(
                f"{endpoint}/versions",
                headers=_build_workflow_write_headers(),
            )
            assert versions.status_code == 200
            assert versions.json() == []
            lifecycle_service.complete(claim, deleted=False)
    finally:
        session_factory.engine.dispose()


def test_application_copy_rejects_internal_lifecycle_namespace_before_claim(
    tmp_path: Path,
) -> None:
    """验证公开 copy 的 source/target 都不能伪装成内部 lifecycle resource。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    endpoint = "/api/v1/workflows/projects/project-1/applications/inspection-api-app"
    reserved_id = f"{WORKFLOW_LIFECYCLE_RESERVED_PREFIX}template__{'a' * 64}"
    try:
        with client:
            saved = client.put(
                endpoint,
                headers=_build_workflow_write_headers(),
                json={
                    "application": _build_application_payload(),
                    "template": _build_template_payload(),
                },
            )
            assert saved.status_code == 201
            target_response = client.post(
                f"{endpoint}/copy",
                headers=_build_workflow_write_headers(),
                json={"target_application_id": reserved_id},
            )
            source_response = client.post(
                f"/api/v1/workflows/projects/project-1/applications/{reserved_id}/copy",
                headers=_build_workflow_write_headers(),
                json={"target_application_id": "normal-target"},
            )
            assert target_response.status_code == 400
            assert source_response.status_code == 400
            assert not dataset_storage.resolve(
                build_application_object_key(
                    project_id="project-1",
                    application_id=reserved_id,
                )
            ).exists()
            with pytest.raises(ResourceNotFoundError):
                WorkflowApplicationLifecycleService(
                    session_factory=session_factory,
                    dataset_storage=dataset_storage,
                ).get(project_id="project-1", application_id=reserved_id)
    finally:
        session_factory.engine.dispose()


def test_committed_marker_never_rolls_back_when_cleanup_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 marker 后清理失败只留待启动 finalize，不改变已提交结果。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    endpoint = "/api/v1/workflows/projects/project-1/applications/inspection-api-app"
    template_payload = _build_template_payload()
    application_payload = _build_application_payload()
    try:
        with client:
            original = client.put(
                endpoint,
                headers=_build_workflow_write_headers(),
                json={"application": application_payload, "template": template_payload},
            )
            assert original.status_code == 201
            next_template = deepcopy(template_payload)
            next_template["display_name"] = "Committed Template"
            next_application = deepcopy(application_payload)
            next_application["display_name"] = "Committed Application"
            original_move_tree = LocalDatasetStorage.move_tree

            def interrupt_active_journal_finalize(
                storage: LocalDatasetStorage,
                source_relative_path: str,
                destination_relative_path: str,
            ) -> None:
                if source_relative_path.startswith(
                    f"{WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT}/"
                ):
                    raise OSError("injected cleanup interruption after commit")
                original_move_tree(
                    storage,
                    source_relative_path,
                    destination_relative_path,
                )

            with monkeypatch.context() as patch:
                patch.setattr(
                    LocalDatasetStorage,
                    "move_tree",
                    interrupt_active_journal_finalize,
                )
                committed = client.put(
                    endpoint,
                    headers=_build_workflow_write_headers(),
                    json={
                        "application": next_application,
                        "template": next_template,
                    },
                )
            assert committed.status_code == 201
            assert committed.json()["application"]["display_name"] == (
                "Committed Application"
            )
            active_journals = tuple(
                dataset_storage.resolve(
                    WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT
                ).iterdir()
            )
            assert len(active_journals) == 1
            assert (active_journals[0] / "committed.json").is_file()

            recovery = WorkflowApplicationBundleJournalService(
                dataset_storage=dataset_storage
            ).recover_interrupted_journals()

            assert recovery.rolled_back_journals == 0
            assert recovery.finalized_journals == 1
            loaded_application = client.get(
                endpoint,
                headers=_build_workflow_write_headers(),
            )
            loaded_template = client.get(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/"
                "versions/1.0.0",
                headers=_build_workflow_write_headers(),
            )
            assert loaded_application.json()["application"]["display_name"] == (
                "Committed Application"
            )
            assert loaded_template.json()["template"]["display_name"] == (
                "Committed Template"
            )
    finally:
        session_factory.engine.dispose()


def test_uncommitted_journal_cleanup_failure_blocks_release_and_later_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未提交 journal 无法删除时必须保留并明确要求恢复。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "storage"))
    )
    journal_service = WorkflowApplicationBundleJournalService(
        dataset_storage=dataset_storage
    )
    authoritative_keys = (
        "workflows/projects/project-1/templates/template-1/versions/1.0.0/template.json",
        "workflows/projects/project-1/templates/template-1/versions/1.0.0/template.summary.json",
        "workflows/projects/project-1/applications/application-1/application.json",
        "workflows/projects/project-1/applications/application-1/application.summary.json",
    )
    for index, object_key in enumerate(authoritative_keys):
        dataset_storage.write_bytes(object_key, f"old-{index}".encode())
    journal = journal_service.prepare(
        operation_id="bundle-cleanup-failure",
        project_id="project-1",
        application_id="application-1",
        template_id="template-1",
        template_version="1.0.0",
    )
    for index, object_key in enumerate(authoritative_keys):
        dataset_storage.write_bytes(object_key, f"new-{index}".encode())

    original_delete_tree = dataset_storage.delete_tree

    def skip_journal_delete(relative_path: str) -> None:
        if relative_path == journal.journal_root_key:
            return
        original_delete_tree(relative_path)

    monkeypatch.setattr(dataset_storage, "delete_tree", skip_journal_delete)
    with pytest.raises(WorkflowRecoveryRequiredError) as rollback_error:
        journal_service.rollback(journal)
    assert rollback_error.value.details == {
        "operation_id": journal.operation_id,
        "journal_root_key": journal.journal_root_key,
        "reason": "journal 目录删除后仍然存在",
    }
    assert dataset_storage.resolve(journal.journal_root_key).is_dir()
    for index, object_key in enumerate(authoritative_keys):
        assert (
            dataset_storage.resolve(object_key).read_bytes() == f"old-{index}".encode()
        )

    for index, object_key in enumerate(authoritative_keys):
        dataset_storage.write_bytes(object_key, f"later-{index}".encode())
    with pytest.raises(WorkflowRecoveryRequiredError):
        journal_service.recover_interrupted_journals()
    assert dataset_storage.resolve(journal.journal_root_key).is_dir()
    for index, object_key in enumerate(authoritative_keys):
        assert (
            dataset_storage.resolve(object_key).read_bytes() == f"old-{index}".encode()
        )
