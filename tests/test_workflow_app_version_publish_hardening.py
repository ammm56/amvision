"""Workflow App 版本发布并发去重和依赖身份专项测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from alembic import command
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from backend.service.application.errors import ResourceConflictError
from backend.service.application.workflows.app_version_service import (
    WorkflowAppVersionService,
    _dependency_fingerprint_payload,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowAppVersionRecord,
)
from backend.service.settings import BackendServiceSettings
from backend.maintenance.database_migrations import _build_alembic_config
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _save_example_documents,
)


def test_concurrent_same_content_publish_creates_only_one_default_version(
    tmp_path: Path,
) -> None:
    """验证同一 Application 并发发布由 lifecycle CAS 立即裁决。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-concurrent-publish.db",
        enable_local_buffer_broker=False,
    )
    try:
        with client:
            _, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            services = tuple(
                WorkflowAppVersionService(
                    session_factory=session_factory,
                    dataset_storage=dataset_storage,
                    node_catalog_registry=client.app.state.node_catalog_registry,
                )
                for _index in range(2)
            )
            draft_fingerprint = (
                services[0]
                .get_draft_snapshot(
                    project_id="project-1",
                    application_id=application.application_id,
                )
                .draft_fingerprint
            )
            entered_publish = Event()
            release_publish = Event()
            original_publish_snapshot = services[0]._publish_snapshot

            def blocked_publish_snapshot(**kwargs):
                entered_publish.set()
                assert release_publish.wait(timeout=10)
                return original_publish_snapshot(**kwargs)

            services[0]._publish_snapshot = blocked_publish_snapshot  # type: ignore[method-assign]

            def publish(index: int) -> object:
                try:
                    return services[index].publish_version(
                        project_id="project-1",
                        application_id=application.application_id,
                        expected_draft_fingerprint=draft_fingerprint,
                        release_notes=f"concurrent-{index}",
                        display_version=None,
                        created_by="test",
                    )
                except ResourceConflictError as error:
                    return error

            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(publish, 0)
                assert entered_publish.wait(timeout=10)
                second = publish(1)
                release_publish.set()
                results = (first.result(timeout=10), second)

        published = [item for item in results if not isinstance(item, Exception)]
        conflicts = [
            item for item in results if isinstance(item, ResourceConflictError)
        ]
        assert len(published) == 1
        assert len(conflicts) == 1
        assert conflicts[0].details["current_operation"] == "publishing"
        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            versions = unit_of_work.workflow_runtime.list_workflow_app_versions(
                "project-1",
                application.application_id,
                include_incomplete=True,
            )
        finally:
            unit_of_work.close()
        assert len(versions) == 1
        assert versions[0].state == "published"
    finally:
        session_factory.engine.dispose()


def test_failed_publish_releases_default_content_claim_and_explicit_duplicate_bypasses_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 failed 可重试，显式重复发布不会争用默认去重键。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-failed-publish-claim.db",
        enable_local_buffer_broker=False,
    )
    try:
        with client:
            _, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            service = WorkflowAppVersionService(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            snapshot = service.get_draft_snapshot(
                project_id="project-1",
                application_id=application.application_id,
            )
            original_move_tree = dataset_storage.move_tree

            def fail_move_once(_source: str, _destination: str) -> None:
                raise OSError("injected move failure")

            monkeypatch.setattr(dataset_storage, "move_tree", fail_move_once)
            with pytest.raises(OSError, match="injected move failure"):
                service.publish_version(
                    project_id="project-1",
                    application_id=application.application_id,
                    expected_draft_fingerprint=snapshot.draft_fingerprint,
                    release_notes="failed publish",
                    display_version=None,
                    created_by="test",
                )
            monkeypatch.setattr(dataset_storage, "move_tree", original_move_tree)
            published = service.publish_version(
                project_id="project-1",
                application_id=application.application_id,
                expected_draft_fingerprint=snapshot.draft_fingerprint,
                release_notes="successful retry",
                display_version=None,
                created_by="test",
            )
            duplicate = service.publish_version(
                project_id="project-1",
                application_id=application.application_id,
                expected_draft_fingerprint=snapshot.draft_fingerprint,
                release_notes="explicit duplicate",
                display_version=None,
                created_by="test",
                allow_duplicate_content=True,
            )

        with session_factory.create_session() as session:
            records = (
                session.execute(
                    select(WorkflowAppVersionRecord).order_by(
                        WorkflowAppVersionRecord.version_number
                    )
                )
                .scalars()
                .all()
            )
        assert [record.state for record in records] == [
            "failed",
            "published",
            "published",
        ]
        assert records[0].content_deduplication_key is None
        assert records[1].content_deduplication_key == snapshot.content_fingerprint
        assert records[2].content_deduplication_key is None
        assert published.workflow_app_version_id != duplicate.workflow_app_version_id
    finally:
        session_factory.engine.dispose()


def test_dependency_manifest_audits_application_binding_resources_and_stable_implementation_identity(
    tmp_path: Path,
) -> None:
    """验证 binding 资源与现有节点版本/manifest 身份均可直接审计。"""

    client, session_factory, dataset_storage = _create_runtime_api_client(
        tmp_path,
        database_name="workflow-app-version-dependency-audit.db",
        enable_local_buffer_broker=False,
    )
    try:
        with client:
            _, application = _save_example_documents(
                client=client,
                dataset_storage=dataset_storage,
                example_name="barcode_result_display",
            )
            bindings = list(application.bindings)
            bindings[0] = bindings[0].model_copy(
                update={
                    "config": {
                        **dict(bindings[0].config),
                        "dependency": {
                            "deployment_instance_id": "deployment-instance-binding-1"
                        },
                    }
                }
            )
            workflow_service = LocalWorkflowJsonService(
                dataset_storage=dataset_storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            )
            workflow_service.save_application(
                project_id="project-1",
                application=application.model_copy(
                    update={"bindings": tuple(bindings)}
                ),
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

        references = snapshot.dependencies["resource_references"]
        assert {
            "path": "application.bindings[0].config.dependency.deployment_instance_id",
            "value": "deployment-instance-binding-1",
        } in references
        pack_fingerprints = {
            item["node_pack_id"]: item["manifest_sha256"]
            for item in snapshot.dependencies["node_packs"]
        }
        saw_core = False
        saw_custom = False
        for node in snapshot.dependencies["nodes"]:
            identity = node["implementation_identity"]
            if node["node_pack_id"] is None:
                saw_core = True
                assert identity == {
                    "source": "node-definition-version",
                    "version": node["version"],
                }
            else:
                saw_custom = True
                assert identity["source"] == "node-pack-manifest"
                assert identity["node_definition_version"] == node["version"]
                assert identity["node_pack_version"] == node["node_pack_version"]
                assert (
                    identity["manifest_sha256"]
                    == pack_fingerprints[node["node_pack_id"]]
                )
        assert saw_core is True
        assert saw_custom is True
        fingerprint_dependencies = _dependency_fingerprint_payload(
            snapshot.dependencies
        )
        assert all(
            "implementation_identity" not in node
            for node in fingerprint_dependencies["nodes"]
        )
        assert all(
            not item["path"].startswith("application.bindings")
            for item in fingerprint_dependencies["resource_references"]
        )
    finally:
        session_factory.engine.dispose()


def test_publish_deduplication_migration_backfills_one_canonical_claim(
    tmp_path: Path,
) -> None:
    """验证历史重复版本可无损迁移，且新唯一占位由数据库强制执行。"""

    database_path = tmp_path / "workflow-app-version-deduplication-migration.db"
    settings = BackendServiceSettings(
        database={"url": f"sqlite:///{database_path.as_posix()}", "echo": False}
    )
    config = _build_alembic_config(settings)
    command.upgrade(config, "f7d1e3a5b9c2")
    session_factory = SessionFactory(settings.to_database_settings())
    try:
        with session_factory.engine.begin() as connection:
            for version_number, state in (
                (1, "published"),
                (2, "archived"),
                (3, "failed"),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO workflow_app_versions (
                            workflow_app_version_id, project_id, application_id,
                            version_number, display_version, release_notes,
                            application_snapshot_object_key, template_snapshot_object_key,
                            contract_snapshot_object_key, dependency_manifest_object_key,
                            content_fingerprint, contract_fingerprint, state, created_at,
                            created_by, completed_at, error
                        ) VALUES (
                            :version_id, 'project-1', 'app-1', :version_number,
                            :display_version, '', :application_key, :template_key,
                            :contract_key, :dependency_key, 'sha256:same',
                            'sha256:contract', :state, '2026-08-19T00:00:00Z',
                            'test', '2026-08-19T00:00:01Z', NULL
                        )
                        """
                    ),
                    {
                        "version_id": f"version-{version_number}",
                        "version_number": version_number,
                        "display_version": f"v{version_number}",
                        "application_key": f"versions/{version_number}/application.json",
                        "template_key": f"versions/{version_number}/template.json",
                        "contract_key": f"versions/{version_number}/contract.json",
                        "dependency_key": f"versions/{version_number}/dependencies.json",
                        "state": state,
                    },
                )
        session_factory.engine.dispose()

        command.upgrade(config, "f8a2c4e6b1d3")
        verification_factory = SessionFactory(settings.to_database_settings())
        try:
            inspector = inspect(verification_factory.engine)
            columns = {
                item["name"] for item in inspector.get_columns("workflow_app_versions")
            }
            assert "content_deduplication_key" in columns
            signatures = {
                tuple(item.get("column_names") or ())
                for item in inspector.get_unique_constraints("workflow_app_versions")
            }
            assert (
                "project_id",
                "application_id",
                "content_deduplication_key",
            ) in signatures
            with verification_factory.engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT workflow_app_version_id, content_deduplication_key
                        FROM workflow_app_versions
                        ORDER BY version_number
                        """
                    )
                ).all()
            assert rows == [
                ("version-1", "sha256:same"),
                ("version-2", None),
                ("version-3", None),
            ]
            with pytest.raises(IntegrityError):
                with verification_factory.engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                            UPDATE workflow_app_versions
                            SET content_deduplication_key = 'sha256:same'
                            WHERE workflow_app_version_id = 'version-2'
                            """
                        )
                    )
        finally:
            verification_factory.engine.dispose()
    finally:
        session_factory.engine.dispose()
