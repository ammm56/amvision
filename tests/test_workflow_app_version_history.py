"""发布历史的命名、删除、不可变快照和引用保护 API 测试。"""

from pathlib import Path
from threading import Event

import pytest

from tests.api_test_support import build_test_headers
from tests.test_workflow_app_version_runtime import _publish_current_draft
from tests.test_workflow_runtime_invoke_api import (
    _create_runtime_api_client,
    _save_example_documents,
)


def test_version_history_rename_delete_and_sequence(tmp_path: Path) -> None:
    """命名不改快照；删除不可恢复且不复用编号，相同内容可重新发布。"""
    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="history.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _, app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            version_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=app.application_id,
                release_notes="baseline",
            )
            base = f"/api/v1/workflows/projects/project-1/applications/{app.application_id}/versions"
            url = f"{base}/{version_id}"
            before = client.get(url, headers=headers).json()
            assert (
                client.patch(
                    url, headers=headers, json={"display_version": "   "}
                ).status_code
                == 400
            )
            assert (
                client.patch(
                    url,
                    headers=headers,
                    json={"display_version": "name", "template": {}},
                ).status_code
                == 422
            )
            assert (
                client.patch(
                    url,
                    headers={"Authorization": "Bearer invalid"},
                    json={"display_version": "name"},
                ).status_code
                == 401
            )
            renamed = client.patch(
                url, headers=headers, json={"display_version": "  现场基线  "}
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["display_version"] == "现场基线"
            assert renamed.json()["release_notes"] == "baseline"
            edited = client.patch(
                url,
                headers=headers,
                json={
                    "display_version": "现场基线",
                    "release_notes": "修改后的版本说明",
                },
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["release_notes"] == "修改后的版本说明"
            assert (
                client.get(url, headers=headers).json()["release_notes"]
                == "修改后的版本说明"
            )
            assert (
                client.patch(
                    url,
                    headers=headers,
                    json={"display_version": "现场基线", "release_notes": "x" * 4097},
                ).status_code
                == 422
            )
            cleared = client.patch(
                url,
                headers=headers,
                json={"display_version": "现场基线", "release_notes": ""},
            )
            assert cleared.status_code == 200
            assert cleared.json()["release_notes"] == ""
            after = client.get(url, headers=headers).json()
            for field in (
                "application",
                "template",
                "manifest",
                "content_fingerprint",
                "version_number",
            ):
                assert after[field] == before[field]
            wrong = url.replace(
                f"applications/{app.application_id}", "applications/other-app"
            )
            assert client.delete(wrong, headers=headers).status_code == 404
            assert client.delete(url, headers=headers).status_code == 204
            assert client.get(base, headers=headers).json() == []
            assert client.get(url, headers=headers).status_code == 404
            assert (
                client.post(
                    url + "/restore",
                    headers=headers,
                    json={"expected_state": "archived"},
                ).status_code
                == 404
            )
            assert (
                client.patch(
                    url, headers=headers, json={"display_version": "revive"}
                ).status_code
                == 404
            )
            next_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=app.application_id,
                release_notes="republish",
            )
            assert (
                client.get(f"{base}/{next_id}", headers=headers).json()[
                    "version_number"
                ]
                == 2
            )
    finally:
        factory.engine.dispose()


def test_versions_and_terminal_runs_do_not_block_physical_application_deletion(
    tmp_path: Path,
) -> None:
    """无 Runtime 时直接物理删除版本、终态执行记录和独占 Template。"""

    from backend.contracts.workflows import (
        build_workflow_preview_run_storage_dir,
        build_workflow_run_storage_dir,
    )
    from backend.service.application.workflows.documents.storage import (
        build_application_prompt_mask_root_key,
        build_template_version_directory_key,
    )
    from backend.service.domain.workflows.workflow_runtime_records import (
        WorkflowPreviewRun,
        WorkflowRun,
    )
    from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="history-application-delete.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            template, app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            version_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=app.application_id,
                release_notes="delete application baseline",
            )
            base = (
                "/api/v1/workflows/projects/project-1/applications/"
                f"{app.application_id}"
            )
            version = client.get(
                f"{base}/versions/{version_id}", headers=headers
            ).json()
            snapshot_paths = tuple(
                storage.resolve(version[key])
                for key in (
                    "application_snapshot_object_key",
                    "template_snapshot_object_key",
                    "contract_snapshot_object_key",
                    "dependency_manifest_object_key",
                )
            )
            assert all(path.is_file() for path in snapshot_paths)

            preview_run_id = "preview-delete-with-application"
            workflow_run_id = "run-delete-with-application"
            unit_of_work = SqlAlchemyUnitOfWork(factory.create_session())
            try:
                unit_of_work.workflow_runtime.save_preview_run(
                    WorkflowPreviewRun(
                        preview_run_id=preview_run_id,
                        project_id="project-1",
                        application_id=app.application_id,
                        source_kind="editor-preview",
                        application_snapshot_object_key=(
                            f"{build_workflow_preview_run_storage_dir(preview_run_id)}"
                            "/application.snapshot.json"
                        ),
                        template_snapshot_object_key=(
                            f"{build_workflow_preview_run_storage_dir(preview_run_id)}"
                            "/template.snapshot.json"
                        ),
                        state="succeeded",
                    )
                )
                unit_of_work.workflow_runtime.save_workflow_run(
                    WorkflowRun(
                        workflow_run_id=workflow_run_id,
                        workflow_runtime_id="removed-runtime",
                        project_id="project-1",
                        application_id=app.application_id,
                        workflow_app_version_id=version_id,
                        state="succeeded",
                    )
                )
                unit_of_work.commit()
            finally:
                unit_of_work.close()
            preview_dir = storage.resolve(
                build_workflow_preview_run_storage_dir(preview_run_id)
            )
            run_dir = storage.resolve(build_workflow_run_storage_dir(workflow_run_id))
            storage.write_json(
                f"{build_workflow_preview_run_storage_dir(preview_run_id)}/result.json",
                {"ok": True},
            )
            storage.write_json(
                f"{build_workflow_run_storage_dir(workflow_run_id)}/result.json",
                {"ok": True},
            )
            template_dir = storage.resolve(
                build_template_version_directory_key(
                    project_id="project-1",
                    template_id=template.template_id,
                    template_version=template.template_version,
                )
            )
            assert preview_dir.is_dir()
            assert run_dir.is_dir()
            assert template_dir.is_dir()
            prompt_mask_root_key = build_application_prompt_mask_root_key(
                project_id="project-1",
                application_id=app.application_id,
            )
            storage.write_bytes(f"{prompt_mask_root_key}/mask.png", b"mask")
            prompt_mask_dir = storage.resolve(prompt_mask_root_key)
            assert prompt_mask_dir.is_dir()

            assert client.delete(base, headers=headers).status_code == 204
            assert client.get(base, headers=headers).status_code == 404
            assert all(not path.exists() for path in snapshot_paths)
            assert not preview_dir.exists()
            assert not run_dir.exists()
            assert not template_dir.exists()
            assert not prompt_mask_dir.exists()
            unit_of_work = SqlAlchemyUnitOfWork(factory.create_session())
            try:
                assert (
                    unit_of_work.workflow_runtime.get_workflow_app_version(version_id)
                    is None
                )
                assert (
                    unit_of_work.workflow_runtime.get_preview_run(preview_run_id)
                    is None
                )
                assert (
                    unit_of_work.workflow_runtime.get_workflow_run(workflow_run_id)
                    is None
                )
                assert (
                    unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                        "project-1", app.application_id
                    )
                    is None
                )
            finally:
                unit_of_work.close()

            saved = client.put(
                base,
                headers=headers,
                json={
                    "application": app.model_dump(mode="json"),
                    "template": template.model_dump(mode="json"),
                },
            )
            assert saved.status_code == 201, saved.text
            next_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=app.application_id,
                release_notes="after application recreation",
            )
            next_version = client.get(f"{base}/versions/{next_id}", headers=headers)
            assert next_version.status_code == 200
            assert next_version.json()["version_number"] == 1
    finally:
        factory.engine.dispose()


def test_version_history_delete_protects_runtime_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有 Runtime 引用时直接拒绝，不能先移走快照再恢复造成读取窗口。"""
    from backend.service.application.workflows import app_version_service

    staged_versions = []
    original_stage = app_version_service.stage_workflow_resource_storage

    def track_stage(**kwargs):
        """记录是否曾移走被 Runtime 依赖的发布快照。"""
        staged_versions.append(kwargs["resource_id"])
        return original_stage(**kwargs)

    monkeypatch.setattr(app_version_service, "stage_workflow_resource_storage", track_stage)
    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="history-references.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _, app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            version_id = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=app.application_id,
                release_notes="baseline",
            )
            url = f"/api/v1/workflows/projects/project-1/applications/{app.application_id}/versions/{version_id}"
            created = client.post(
                "/api/v1/workflows/app-runtimes",
                headers=headers,
                json={
                    "project_id": "project-1",
                    "workflow_app_version_id": version_id,
                    "display_name": "reference test",
                },
            )
            assert created.status_code == 201, created.text
            for state in ("published", "archived"):
                if state == "archived":
                    assert (
                        client.post(
                            url + "/archive",
                            headers=headers,
                            json={"expected_state": "published"},
                        ).status_code
                        == 200
                    )
                response = client.delete(url, headers=headers)
                assert response.status_code == 409, response.text
                assert response.json()["error"]["details"]["runtime_revisions"] == 1
                assert client.get(url, headers=headers).json()["state"] == state
                assert staged_versions == [], "被引用版本的快照不得出现短暂不可读窗口"
    finally:
        factory.engine.dispose()


def test_application_delete_preserves_template_shared_by_another_workflow(
    tmp_path: Path,
) -> None:
    """删除 Workflow 时只清理独占 Template，共享 Template 保持可读。"""

    from backend.service.application.workflows.documents.storage import (
        build_template_version_directory_key,
    )

    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="history-shared-template.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            template, first_app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            second_app = first_app.model_copy(
                update={
                    "application_id": "workflow-app-shared-template",
                    "display_name": "Shared Template Workflow",
                }
            )
            second_base = (
                "/api/v1/workflows/projects/project-1/applications/"
                f"{second_app.application_id}"
            )
            saved = client.put(
                second_base,
                headers=headers,
                json={
                    "application": second_app.model_dump(mode="json"),
                    "template": template.model_dump(mode="json"),
                },
            )
            assert saved.status_code == 201, saved.text
            template_dir = storage.resolve(
                build_template_version_directory_key(
                    project_id="project-1",
                    template_id=template.template_id,
                    template_version=template.template_version,
                )
            )
            assert template_dir.is_dir()

            first_base = (
                "/api/v1/workflows/projects/project-1/applications/"
                f"{first_app.application_id}"
            )
            assert client.delete(first_base, headers=headers).status_code == 204
            assert template_dir.is_dir()
            assert client.get(second_base, headers=headers).status_code == 200
    finally:
        factory.engine.dispose()


def test_application_delete_rejects_active_preview_without_moving_files(
    tmp_path: Path,
) -> None:
    """活动 Preview 存在时删除返回冲突，数据库和草稿目录保持不变。"""

    from backend.contracts.workflows import build_workflow_preview_run_storage_dir
    from backend.service.domain.workflows.workflow_runtime_records import (
        WorkflowPreviewRun,
    )
    from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="history-active-preview.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _, app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            preview_run_id = "preview-active-delete-guard"
            preview_dir_key = build_workflow_preview_run_storage_dir(preview_run_id)
            unit_of_work = SqlAlchemyUnitOfWork(factory.create_session())
            try:
                unit_of_work.workflow_runtime.save_preview_run(
                    WorkflowPreviewRun(
                        preview_run_id=preview_run_id,
                        project_id="project-1",
                        application_id=app.application_id,
                        source_kind="editor-preview",
                        application_snapshot_object_key=(
                            f"{preview_dir_key}/application.snapshot.json"
                        ),
                        template_snapshot_object_key=(
                            f"{preview_dir_key}/template.snapshot.json"
                        ),
                        state="running",
                    )
                )
                unit_of_work.commit()
            finally:
                unit_of_work.close()
            storage.write_json(f"{preview_dir_key}/state.json", {"state": "running"})
            preview_dir = storage.resolve(preview_dir_key)
            app_base = (
                "/api/v1/workflows/projects/project-1/applications/"
                f"{app.application_id}"
            )

            response = client.delete(app_base, headers=headers)
            assert response.status_code == 409, response.text
            assert response.json()["error"]["details"]["preview_runs"] == [
                {"preview_run_id": preview_run_id, "state": "running"}
            ]
            assert client.get(app_base, headers=headers).status_code == 200
            assert preview_dir.is_dir()
    finally:
        factory.engine.dispose()


def test_application_delete_startup_recovery_restores_uncommitted_storage(
    tmp_path: Path,
) -> None:
    """删除提交前中断时，启动恢复目录并释放同一 Application claim。"""

    from backend.service.application.workflows.application_deletion import (
        WorkflowApplicationDeletionService,
    )
    from backend.service.application.workflows.application_lifecycle import (
        WorkflowApplicationLifecycleService,
    )
    from backend.service.application.workflows.documents.storage import (
        build_application_directory_key,
    )
    from backend.service.application.workflows.resource_deletion_staging import (
        stage_workflow_resource_storage,
    )
    from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    client, factory, storage = _create_runtime_api_client(
        tmp_path,
        database_name="history-application-delete-recovery.db",
        enable_local_buffer_broker=False,
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _, app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            app_dir_key = build_application_directory_key(
                project_id="project-1",
                application_id=app.application_id,
            )
            claim = WorkflowApplicationLifecycleService(
                session_factory=factory,
                dataset_storage=storage,
            ).acquire(
                project_id="project-1",
                application_id=app.application_id,
                operation="deleting",
            )
            assert claim.operation_id is not None
            staging = stage_workflow_resource_storage(
                dataset_storage=storage,
                operation_id=claim.operation_id,
                resource_kind="workflow-application",
                resource_id=app.application_id,
                source_paths=(app_dir_key,),
                metadata={
                    "project_id": "project-1",
                    "application_id": app.application_id,
                },
            )
            assert not storage.resolve(app_dir_key).exists()

            recovery = WorkflowApplicationDeletionService(
                session_factory=factory,
                dataset_storage=storage,
                node_catalog_registry=client.app.state.node_catalog_registry,
            ).recover_interrupted_deletions()

            assert recovery.restored_deletions == 1
            assert recovery.completed_cleanups == 0
            assert storage.resolve(app_dir_key).is_dir()
            assert not storage.resolve(staging.staging_root).exists()
            assert (
                client.get(
                    (
                        "/api/v1/workflows/projects/project-1/applications/"
                        f"{app.application_id}"
                    ),
                    headers=headers,
                ).status_code
                == 200
            )
            unit_of_work = SqlAlchemyUnitOfWork(factory.create_session())
            try:
                lifecycle = (
                    unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                        "project-1", app.application_id
                    )
                )
            finally:
                unit_of_work.close()
            assert lifecycle is not None
            assert lifecycle.state == "idle"
            assert lifecycle.deleted is False
    finally:
        factory.engine.dispose()


def test_delete_preserves_run_provenance_without_runtime(tmp_path: Path) -> None:
    """Runtime 已移除但 Run 仍保存版本来源时，不能删除版本。"""
    from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
    from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

    client, factory, storage = _create_runtime_api_client(
        tmp_path, database_name="history-runs.db", enable_local_buffer_broker=False
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    try:
        with client:
            _, app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            vid = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=app.application_id,
                release_notes="run origin",
            )
            uow = SqlAlchemyUnitOfWork(factory.create_session())
            try:
                uow.workflow_runtime.save_workflow_run(
                    WorkflowRun(
                        workflow_run_id="retained-run",
                        workflow_runtime_id="removed-runtime",
                        project_id="project-1",
                        application_id=app.application_id,
                        workflow_app_version_id=vid,
                        state="succeeded",
                    )
                )
                uow.commit()
            finally:
                uow.close()
            url = f"/api/v1/workflows/projects/project-1/applications/{app.application_id}/versions/{vid}"
            response = client.delete(url, headers=headers)
            assert response.status_code == 409
            assert response.json()["error"]["details"]["runs"] == 1
            assert client.get(url, headers=headers).status_code == 200
    finally:
        factory.engine.dispose()


@pytest.mark.parametrize("delete_first", [True, False])
def test_delete_and_runtime_create_are_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delete_first: bool
) -> None:
    """Runtime 创建持有 Application claim 时，版本删除确定返回冲突。"""
    from backend.service.infrastructure.persistence.workflow_runtime_repository import (
        SqlAlchemyWorkflowRuntimeRepository,
    )
    from tests.test_workflow_app_version_archive_races import _start_call, _finish_call

    client, factory, storage = _create_runtime_api_client(
        tmp_path, database_name="history-race.db", enable_local_buffer_broker=False
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    entered, release = Event(), Event()
    original = SqlAlchemyWorkflowRuntimeRepository.fence_published_workflow_app_version
    try:
        with client:
            _, app = _save_example_documents(
                client=client,
                dataset_storage=storage,
                example_name="barcode_result_display",
            )
            vid = _publish_current_draft(
                client=client,
                headers=headers,
                application_id=app.application_id,
                release_notes="race",
            )
            url = f"/api/v1/workflows/projects/project-1/applications/{app.application_id}/versions/{vid}"

            def fence(repository, version_id):
                if version_id != vid:
                    return original(repository, version_id)
                result = None if delete_first else original(repository, version_id)
                entered.set()
                assert release.wait(timeout=10)
                return original(repository, version_id) if delete_first else result

            monkeypatch.setattr(
                SqlAlchemyWorkflowRuntimeRepository,
                "fence_published_workflow_app_version",
                fence,
            )
            create_thread, create_result = _start_call(
                lambda: client.post(
                    "/api/v1/workflows/app-runtimes",
                    headers=headers,
                    json={
                        "project_id": "project-1",
                        "workflow_app_version_id": vid,
                        "display_name": "race",
                    },
                )
            )
            assert entered.wait(timeout=10)
            if delete_first:
                deleted = client.delete(url, headers=headers)
                release.set()
            else:
                delete_thread, delete_result = _start_call(
                    lambda: client.delete(url, headers=headers)
                )
                release.set()
                deleted = _finish_call(delete_thread, delete_result)
            created = _finish_call(create_thread, create_result)
            assert deleted.status_code == 409
            assert created.status_code == 201
            assert client.get(url, headers=headers).status_code == 200
    finally:
        release.set()
        factory.engine.dispose()
