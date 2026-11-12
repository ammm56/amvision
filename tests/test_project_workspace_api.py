"""项目工作区元数据、范围导出和删除回执回归。"""

from uuid import uuid4
from pathlib import Path
import pytest

from backend.service.application.project_deletion import ProjectDeletionService

from tests.test_project_resources_api import _create_project_resources_test_client
from tests.test_sdk_config_packages_api import (
    _create_sdk_config_package_test_client,
    _seed_workflow_runtime_and_trigger_source,
)
from tests.api_test_support import (
    build_test_headers,
    build_bearer_headers,
    issue_test_user_token,
)


def test_workspace_metadata_search_revision_and_deletion_receipt(
    tmp_path: Path,
) -> None:
    """完整检查创建、查询、编辑冲突、授权和删除后回执，不重启同一容器。"""
    client, factory = _create_project_resources_test_client(
        tmp_path, database_name="workspace.db"
    )
    headers = build_test_headers(scopes="*")
    try:
        with client:
            body = {
                "request_id": str(uuid4()),
                "display_name": "界面验收",
                "description": "独立测试项目",
            }
            created = client.post("/api/v1/projects", headers=headers, json=body)
            assert created.status_code == 201, created.text
            project = created.json()
            base = f"/api/v1/projects/{project['project_id']}"
            assert (
                client.post("/api/v1/projects", headers=headers, json=body).json()[
                    "project_id"
                ]
                == project["project_id"]
            )
            changed = {
                "display_name": "修改名称",
                "description": None,
                "expected_revision": project["revision"],
            }
            updated = client.patch(base, headers=headers, json=changed)
            assert updated.status_code == 200, updated.text
            assert updated.json()["created_at"] == project["created_at"]
            assert updated.json()["revision"] != project["revision"]
            assert client.patch(base, headers=headers, json=changed).status_code == 409
            assert (
                client.patch(
                    base, headers=headers, json={**changed, "display_name": " "}
                ).status_code
                == 400
            )
            page = client.get(
                "/api/v1/projects",
                headers=headers,
                params={"q": "修改", "include_summary": True, "limit": 1},
            )
            assert page.status_code == 200 and page.headers["x-total-count"] == "1"
            assert page.json()[0]["model_total"] == 0
            overview = client.get(base + "/overview", headers=headers)
            assert overview.status_code == 200
            assert overview.json()["recent"] == [] and overview.json()["active"] == []
            assert overview.json()["total"] == 0 and overview.json()["checked_at"]
            token = issue_test_user_token(
                factory,
                username="workspace-reader",
                scopes=("workflows:read", "models:read"),
                project_ids=(project["project_id"],),
            )
            assert (
                client.patch(
                    base, headers=build_bearer_headers(token), json=changed
                ).status_code
                == 403
            )
            assert (
                client.get(
                    "/api/v1/projects/project-1/overview",
                    headers=build_bearer_headers(token),
                ).status_code
                == 403
            )
            assert (
                client.request(
                    "DELETE",
                    base,
                    headers=headers,
                    json={"confirmation": project["project_id"] + " "},
                ).status_code
                == 400
            )
            deleted = client.request(
                "DELETE",
                base,
                headers=headers,
                json={"confirmation": project["project_id"]},
            )
            assert deleted.status_code == 202, deleted.text
            receipt_url = (
                base + "/deletion-operations/" + deleted.json()["operation_id"]
            )
            assert client.get(receipt_url, headers=headers).json()["state"] == "deleted"
            assert (
                client.get(receipt_url, headers=build_bearer_headers(token)).status_code
                == 403
            )
            assert client.get(base, headers=headers).status_code == 404
    finally:
        factory.engine.dispose()


def test_sdk_scope_dependency_and_revision_guard(tmp_path: Path) -> None:
    """Trigger 自动关联 Runtime；空选择、失效资源和过期预览不得错误下载。"""
    client, factory, storage = _create_sdk_config_package_test_client(tmp_path)
    _seed_workflow_runtime_and_trigger_source(factory, storage)
    headers = build_test_headers(scopes="*")
    base = "/api/v1/projects/project-1/sdk-config-packages"
    try:
        with client:
            resources = client.get(base + "/resources", headers=headers)
            assert resources.status_code == 200, resources.text
            trigger = next(
                item for item in resources.json() if item["kind"] == "trigger"
            )
            selected = {
                "runtime_ids": [],
                "trigger_source_ids": [trigger["id"]],
                "deployment_ids": [],
                "include_access_token": False,
            }
            preview = client.post(base + "/preview", headers=headers, json=selected)
            assert preview.status_code == 200, preview.text
            assert preview.json()["workflow_runtime_count"] == 1
            assert preview.json()["trigger_source_count"] == 1
            assert (
                client.post(
                    base + "/download",
                    headers=headers,
                    json={**selected, "expected_revision": "0" * 64},
                ).status_code
                == 409
            )
            assert (
                client.post(
                    base + "/download",
                    headers=headers,
                    json={
                        **selected,
                        "expected_revision": preview.json()["configuration_revision"],
                    },
                ).status_code
                == 200
            )
            assert (
                client.post(
                    base + "/preview",
                    headers=headers,
                    json={**selected, "runtime_ids": ["other-project-runtime"]},
                ).status_code
                == 400
            )
            empty = {**selected, "trigger_source_ids": []}
            assert (
                client.post(base + "/preview", headers=headers, json=empty).json()[
                    "files"
                ]
                == []
            )
            assert (
                client.post(base + "/download", headers=headers, json=empty).status_code
                == 400
            )
    finally:
        factory.engine.dispose()


def test_cleanup_failure_receipt_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文件占用失败不能误报完成；释放占用后恢复清理且不影响其他项目。"""
    client, factory, storage = _create_project_resources_test_client(
        tmp_path,
        database_name="cleanup-receipt.db",
        include_storage=True,
        project_items=[],
    )
    headers = build_test_headers(scopes="*")
    try:
        with client:
            response = client.post(
                "/api/v1/projects/bootstrap",
                headers=headers,
                json={"project_id": "project-cleanup"},
            )
            assert response.status_code == 201
            storage.write_bytes("projects/project-cleanup/results/test.txt", b"test")
            storage.write_bytes("projects/project-keep/results/test.txt", b"keep")
            service = ProjectDeletionService(
                session_factory=factory,
                dataset_storage=storage,
                queue_backend=client.app.state.queue_backend,
                default_project_id="project-1",
                configured_project_ids=(),
            )
            result = service.delete(
                project_id="project-cleanup",
                project_source="local_disk",
                confirmation="project-cleanup",
                requested_by="test-principal",
            )
            assert (
                service.get_deletion_result("project-cleanup", "latest")["state"]
                == "cleanup_pending"
            )
            original = storage.delete_tree

            def fail_cleanup(key: str) -> None:
                """仅注入当前隔离目录的删除占用错误。"""
                if key == result.cleanup_object_key:
                    raise PermissionError("文件正在使用")
                original(key)

            with monkeypatch.context() as patch:
                patch.setattr(storage, "delete_tree", fail_cleanup)
                with pytest.raises(PermissionError):
                    service.cleanup(
                        result.cleanup_object_key, result.project_id, result.task_ids
                    )
            receipt = service.get_deletion_result(
                "project-cleanup", result.operation_id
            )
            assert receipt["state"] == "cleanup_failed"
            assert "文件正在使用" in receipt["cleanup_error"]
            recovered = service.recover_interrupted_deletions()
            assert recovered.completed_cleanups == 1
            receipt = service.get_deletion_result(
                "project-cleanup", result.operation_id
            )
            assert receipt["state"] == "deleted" and "cleanup_error" not in receipt
            assert (
                storage.resolve("projects/project-keep/results/test.txt").read_bytes()
                == b"keep"
            )
    finally:
        factory.engine.dispose()


def test_overview_preserves_deployment_modes(tmp_path: Path) -> None:
    """同一部署的两种运行模式保持独立身份，停止中也不能从当前服务中消失。"""
    from backend.service.infrastructure.persistence.deployment_orm import (
        DeploymentInstanceRecord,
        DeploymentRuntimeStateRecord,
    )
    from backend.service.infrastructure.persistence.project_summary_repository import (
        SqlAlchemyProjectSummaryRepository,
    )

    _, factory = _create_project_resources_test_client(
        tmp_path, database_name="overview-modes.db"
    )
    try:
        with factory.create_session() as session:
            session.add(
                DeploymentInstanceRecord(
                    deployment_instance_id="deployment-ui",
                    project_id="project-1",
                    model_id="model-ui",
                    model_version_id="version-ui",
                    runtime_backend="onnx",
                    device_name="cpu",
                    runtime_configuration_json={},
                    status="ready",
                    display_name="测试部署",
                    created_at="2026-11-04T00:00:00Z",
                    updated_at="2026-11-04T00:00:00Z",
                )
            )
            session.flush()
            for mode, state in (("sync", "running"), ("async", "stopping")):
                session.add(
                    DeploymentRuntimeStateRecord(
                        deployment_instance_id="deployment-ui",
                        runtime_mode=mode,
                        desired_state="running",
                        observed_state=state,
                        created_at="2026-11-04T00:00:00Z",
                        updated_at="2026-11-04T00:00:00Z",
                    )
                )
            session.commit()
            result = SqlAlchemyProjectSummaryRepository(session).get_overview(
                "project-1"
            )
            assert {
                (row["runtime_mode"], row["state"]) for row in result["active"]
            } == {
                ("sync", "running"),
                ("async", "stopping"),
            }
    finally:
        factory.engine.dispose()


def test_workspace_permissions_activity_pagination_and_partial_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """按资源权限裁剪目录、分页与版本来源；局部损坏不伪报为空。"""
    from backend.service.infrastructure.persistence.dataset_orm import (
        DatasetVersionRecord,
    )
    from backend.service.infrastructure.persistence.model_orm import (
        ModelRecord,
        ModelVersionRecord,
    )
    from backend.service.application.project_summary import ProjectSummaryService
    from backend.service.api.rest.v1.routes.projects.access import (
        project_resource_access,
    )
    from types import SimpleNamespace

    client, factory = _create_project_resources_test_client(
        tmp_path, database_name="workspace-access.db"
    )
    headers = build_test_headers(scopes="*")
    try:
        with client:
            with factory.create_session() as session:
                session.add_all(
                    [
                        DatasetVersionRecord(
                            dataset_version_id=f"version-{index:03}",
                            version_number=index + 1,
                            dataset_id="fixture",
                            project_id="project-1",
                            task_type="detection",
                            metadata_json={
                                "created_at": f"2026-11-04T00:00:{index:02}Z"
                            },
                        )
                        for index in range(25)
                    ]
                )
                session.add(
                    ModelRecord(
                        model_id="test-model",
                        project_id="project-1",
                        owner_key="project-1",
                        scope_kind="project",
                        model_name="审核模型",
                        model_type="yolo11",
                        task_type="detection",
                        model_scale="n",
                    )
                )
                session.flush()
                session.add(
                    ModelVersionRecord(
                        model_version_id="test-model-version",
                        model_id="test-model",
                        source_kind="import",
                        metadata_json={},
                    )
                )
                session.commit()
            base = "/api/v1/projects/project-1"
            dataset_headers = build_bearer_headers(
                issue_test_user_token(
                    factory,
                    username="dataset-only",
                    scopes=("datasets:read",),
                    project_ids=("project-1",),
                )
            )
            metadata = client.get(base, headers=dataset_headers)
            assert metadata.status_code == 200, metadata.text
            assert set(metadata.json()["resource_counts"]) == {"datasets"}
            assert (
                metadata.json()["summary"] is None
                and metadata.json()["model_total"] is None
            )
            assert (
                client.get(
                    base + "/sdk-config-packages/resources", headers=dataset_headers
                ).status_code
                == 403
            )
            first = client.get(
                base + "/overview?limit=20", headers=dataset_headers
            ).json()
            second = client.get(
                base + "/overview?limit=20&offset=20", headers=dataset_headers
            ).json()
            assert (
                first["total"] == 25
                and len(first["recent"]) == 20
                and len(second["recent"]) == 5
            )
            assert first["recent"][0]["resource_id"] == "version-024"
            assert (
                len(
                    {item["resource_id"] for item in first["recent"] + second["recent"]}
                )
                == 25
            )
            assert all(item["target_id"] == "fixture" for item in first["recent"])
            assert not first["active"] and not first["access"]["models"]
            searched = client.get(
                base + "/overview?q=version-024&kind=datasets", headers=headers
            ).json()
            assert searched["total"] == 1
            model = client.get(base + "/overview?kind=models", headers=headers).json()[
                "recent"
            ]
            assert model[0]["name"] == "审核模型" and model[0]["occurred_at"] == ""
            access = project_resource_access(
                SimpleNamespace(scopes=("*",), allowed_pages=("projects", "datasets"))
            )
            assert access["datasets"] and not any(
                value for key, value in access.items() if key != "datasets"
            )
            with monkeypatch.context() as patch:
                patch.setattr(
                    ProjectSummaryService, "get_model_total", lambda *args: 123
                )
                patch.setattr(
                    ProjectSummaryService,
                    "get_project_summary",
                    lambda *args: (_ for _ in ()).throw(OSError("summary unavailable")),
                )
                recovered = client.get(base, headers=headers)
                assert (
                    recovered.status_code == 200
                    and recovered.json()["resource_counts"]["models"] == 1
                )
                assert "summary" in recovered.json()["resource_errors"]
    finally:
        factory.engine.dispose()


def test_sdk_resource_pages_and_explicit_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """目录分页不加载运行配置；容量边界不允许悄悄截断完整导出。"""
    from backend.service.infrastructure.persistence.workflow_runtime_orm import (
        WorkflowAppRuntimeRecord,
    )
    from backend.service.infrastructure.persistence import (
        project_sdk_resource_repository as resource_module,
    )

    client, factory = _create_project_resources_test_client(
        tmp_path, database_name="sdk-pages.db"
    )
    headers = build_test_headers(scopes="*")
    try:
        with client:
            with factory.create_session() as session:
                session.add_all(
                    [
                        WorkflowAppRuntimeRecord(
                            workflow_runtime_id=f"runtime-{i:03}",
                            project_id="project-1",
                            application_id="app-ui",
                            display_name=f"运行实例 {i}",
                            application_snapshot_object_key="missing-app.json",
                            template_snapshot_object_key="missing-template.json",
                            desired_state="stopped",
                            observed_state="stopped",
                            created_at="2026-11-04T00:00:00Z",
                            updated_at="2026-11-04T00:00:00Z",
                        )
                        for i in range(205)
                    ]
                )
                session.commit()
            url = "/api/v1/projects/project-1/sdk-config-packages/resources"
            page1 = client.get(url, headers=headers)
            page2 = client.get(url + "?offset=200", headers=headers)
            assert page1.status_code == 200 and len(page1.json()) == 200
            assert (
                page1.headers["x-total-count"] == "205"
                and page1.headers["x-has-more"] == "true"
            )
            assert len(page2.json()) == 5 and page2.headers["x-has-more"] == "false"
            assert set(page1.json()[0]) == {"id", "name", "kind", "runtime_id"}
            assert len({row["id"] for row in page1.json() + page2.json()}) == 205
            assert client.get(url + "?limit=201", headers=headers).status_code == 422
            monkeypatch.setattr(resource_module, "SDK_RESOURCE_LIMIT", 204)
            over = client.get(url, headers=headers)
            assert over.status_code == 400 and "204" in over.text
            assert (
                client.post(
                    url.removesuffix("resources") + "preview", headers=headers, json={}
                ).status_code
                == 400
            )
    finally:
        factory.engine.dispose()
