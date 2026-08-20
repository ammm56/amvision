"""Workflow Application 持久化 lifecycle CAS 专项测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from backend.service.application.errors import (
    ResourceConflictError,
    ResourceInUseError,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_lifecycle_resource_key,
)
from backend.service.application.workflows.app_version_service import (
    WorkflowAppVersionService,
)
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_workflows_api import (
    _build_application_payload,
    _build_template_payload,
    _build_workflow_write_headers,
    _create_test_client,
)


def test_application_mutations_reject_every_competing_persistent_claim(
    tmp_path: Path,
) -> None:
    """验证 save/publish/delete 在同一 App 状态门下立即冲突，不等待或排队。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    application_id = "inspection-api-app"
    try:
        with client:
            client.put(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_write_headers(),
                json={"template": _build_template_payload()},
            )
            saved = client.put(
                f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                headers=_build_workflow_write_headers(),
                json={"application": _build_application_payload()},
            )
            assert saved.status_code == 201
            draft_fingerprint = saved.json()["draft_fingerprint"]
            lifecycle_service = WorkflowApplicationLifecycleService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
            )

            for operation in ("saving", "publishing", "deleting"):
                claim = lifecycle_service.acquire(
                    project_id="project-1",
                    application_id=application_id,
                    operation=operation,
                )
                try:
                    save_response = client.put(
                        f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                        headers=_build_workflow_write_headers(),
                        json={"application": _build_application_payload()},
                    )
                    publish_response = client.post(
                        f"/api/v1/workflows/projects/project-1/applications/{application_id}/versions",
                        headers=_build_workflow_write_headers(),
                        json={
                            "expected_draft_fingerprint": draft_fingerprint,
                            "release_notes": "must conflict",
                        },
                    )
                    delete_response = client.delete(
                        f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                        headers=_build_workflow_write_headers(),
                    )
                    assert save_response.status_code == 409
                    assert publish_response.status_code == 409
                    assert delete_response.status_code == 409
                    for response in (
                        save_response,
                        publish_response,
                        delete_response,
                    ):
                        details = response.json()["error"]["details"]
                        assert details["current_operation"] == operation
                finally:
                    lifecycle_service.complete(claim, deleted=False)

            deleted = client.delete(
                f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                headers=_build_workflow_write_headers(),
            )
            assert deleted.status_code == 204
            tombstone = lifecycle_service.get(
                project_id="project-1",
                application_id=application_id,
            )
            assert tombstone.deleted is True
            recreated = client.put(
                f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                headers=_build_workflow_write_headers(),
                json={"application": _build_application_payload()},
            )
            assert recreated.status_code == 201
            restored = lifecycle_service.get(
                project_id="project-1",
                application_id=application_id,
            )
            assert restored.deleted is False
            assert restored.generation > tombstone.generation
    finally:
        session_factory.engine.dispose()


def test_publish_record_exists_before_staging_and_failure_releases_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 publishing 记录先于 staging，写盘失败后状态与状态门都可重试。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    application_id = "inspection-api-app"
    try:
        with client:
            client.put(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_write_headers(),
                json={"template": _build_template_payload()},
            )
            saved = client.put(
                f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                headers=_build_workflow_write_headers(),
                json={"application": _build_application_payload()},
            )
            version_service = WorkflowAppVersionService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )

            def assert_record_then_fail(**_kwargs: object) -> None:
                unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
                try:
                    versions = unit_of_work.workflow_runtime.list_workflow_app_versions(
                        "project-1",
                        application_id,
                        include_incomplete=True,
                    )
                finally:
                    unit_of_work.close()
                assert len(versions) == 1
                assert versions[0].state == "publishing"
                raise OSError("injected staging failure")

            monkeypatch.setattr(
                version_service,
                "_write_and_verify_staging",
                assert_record_then_fail,
            )
            with pytest.raises(OSError, match="injected staging failure"):
                version_service.publish_version(
                    project_id="project-1",
                    application_id=application_id,
                    expected_draft_fingerprint=saved.json()["draft_fingerprint"],
                    release_notes="failure before staging",
                    display_version=None,
                    created_by="test",
                )
            delete_response = client.delete(
                f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                headers=_build_workflow_write_headers(),
            )
            assert delete_response.status_code == 204

        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            versions = unit_of_work.workflow_runtime.list_workflow_app_versions(
                "project-1",
                application_id,
                include_incomplete=True,
            )
            lifecycle = (
                unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                    "project-1",
                    application_id,
                )
            )
        finally:
            unit_of_work.close()
        assert [item.state for item in versions] == ["failed"]
        assert lifecycle is not None
        assert lifecycle.state == "idle"
        assert lifecycle.operation_id is None
        assert lifecycle.deleted is True
        staging_root = dataset_storage.resolve(
            f"workflows/projects/project-1/applications/{application_id}/versions/.staging"
        )
        assert not staging_root.exists() or not tuple(staging_root.iterdir())
    finally:
        session_factory.engine.dispose()


def test_startup_recovery_fences_stale_completion_and_removes_orphan_staging(
    tmp_path: Path,
) -> None:
    """验证启动恢复收敛 claim，旧 generation 无法释放新操作，并清理孤儿 staging。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    application_id = "inspection-api-app"
    try:
        with client:
            client.put(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_write_headers(),
                json={"template": _build_template_payload()},
            )
            client.put(
                f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                headers=_build_workflow_write_headers(),
                json={"application": _build_application_payload()},
            )
            lifecycle_service = WorkflowApplicationLifecycleService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
            )
            stale_claim = lifecycle_service.acquire(
                project_id="project-1",
                application_id=application_id,
                operation="saving",
            )
            recovered = lifecycle_service.recover_interrupted_operations()
            assert recovered.scanned_operations == 1
            assert recovered.recovered_operations == 1

            current_claim = lifecycle_service.acquire(
                project_id="project-1",
                application_id=application_id,
                operation="saving",
            )
            with pytest.raises(ResourceConflictError):
                lifecycle_service.complete(stale_claim, deleted=False)
            current = lifecycle_service.get(
                project_id="project-1",
                application_id=application_id,
            )
            assert current.operation_id == current_claim.operation_id
            assert current.generation == current_claim.generation
            lifecycle_service.complete(current_claim, deleted=False)

            orphan_key = (
                f"workflows/projects/project-1/applications/{application_id}/"
                "versions/.staging/orphan-version/manifest.json"
            )
            dataset_storage.write_json(orphan_key, {"complete": False})
            version_service = WorkflowAppVersionService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            version_recovery = version_service.recover_incomplete_versions()
            assert version_recovery.scanned_versions == 0
            assert version_recovery.cleaned_staging_directories == 1
            assert not dataset_storage.resolve(orphan_key).exists()
    finally:
        session_factory.engine.dispose()


def test_backend_bootstrap_recovers_interrupted_application_claim(
    tmp_path: Path,
) -> None:
    """验证真实 backend bootstrap 在接收新请求前释放中断 claim。"""

    first_client, first_factory, dataset_storage = _create_test_client(tmp_path)
    application_id = "inspection-api-app"
    try:
        with first_client:
            first_client.put(
                "/api/v1/workflows/projects/project-1/templates/inspection-demo/versions/1.0.0",
                headers=_build_workflow_write_headers(),
                json={"template": _build_template_payload()},
            )
            first_client.put(
                f"/api/v1/workflows/projects/project-1/applications/{application_id}",
                headers=_build_workflow_write_headers(),
                json={"application": _build_application_payload()},
            )
            lifecycle_service = WorkflowApplicationLifecycleService(
                session_factory=first_factory,
                dataset_storage=dataset_storage,
            )
            interrupted = lifecycle_service.acquire(
                project_id="project-1",
                application_id=application_id,
                operation="saving",
            )
            assert interrupted.state == "saving"
    finally:
        first_factory.engine.dispose()

    second_client, second_factory, _second_storage = _create_test_client(tmp_path)
    try:
        with second_client:
            recovered_service = WorkflowApplicationLifecycleService(
                session_factory=second_factory,
                dataset_storage=dataset_storage,
            )
            recovered = recovered_service.get(
                project_id="project-1",
                application_id=application_id,
            )
            assert recovered.state == "idle"
            assert recovered.operation_id is None
            assert recovered.deleted is False
            assert recovered.generation == interrupted.generation
    finally:
        second_factory.engine.dispose()


def test_project_mutation_fence_orders_admission_without_serializing_bodies(
    tmp_path: Path,
) -> None:
    """验证普通 body 可并行，删除与任一 in-flight mutation 立即互斥。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    service = WorkflowApplicationLifecycleService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    release = Event()
    entered = (Event(), Event())
    resource_keys = (
        build_workflow_lifecycle_resource_key("runtime", "runtime-a"),
        build_workflow_lifecycle_resource_key("trigger", "trigger-b"),
    )

    def hold_mutation(index: int) -> None:
        with service.operation(
            project_id="project-1",
            application_id=resource_keys[index],
            operation="saving",
            allow_deleted=True,
            deleted_on_success=None,
        ):
            entered[index].set()
            assert release.wait(timeout=5)

    try:
        with client, ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(hold_mutation, index) for index in range(2))
            assert entered[0].wait(timeout=5)
            assert entered[1].wait(timeout=5)
            with pytest.raises(ResourceInUseError):
                service.acquire_project_deletion(project_id="project-1")
            release.set()
            for future in futures:
                future.result(timeout=5)

            deletion_claim = service.acquire_project_deletion(project_id="project-1")
            try:
                with pytest.raises(ResourceConflictError):
                    service.acquire(
                        project_id="project-1",
                        application_id=resource_keys[0],
                        operation="saving",
                        allow_deleted=True,
                    )
            finally:
                service.complete(deletion_claim, deleted=False)
    finally:
        release.set()
        session_factory.engine.dispose()


def test_lifecycle_resource_key_respects_database_column_limit() -> None:
    """验证通用 reserved key 在合法 kind 极限时仍不超过 128 字符。"""

    key = build_workflow_lifecycle_resource_key("a" * 31, "resource")
    assert len(key) == 128
    with pytest.raises(ValueError, match="最多 31 位"):
        build_workflow_lifecycle_resource_key("a" * 32, "resource")
