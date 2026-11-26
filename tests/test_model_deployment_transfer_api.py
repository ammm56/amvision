"""真实 HTTP 上传、分析、幂等提交和导出回读验证。"""

from backend.contracts.deployments.model_package import ImportOptions
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.domain.deployments.deployment_runtime_configuration import build_default_runtime_configuration, serialize_deployment_runtime_configuration
from backend.service.infrastructure.object_store.model_package_archive import write_package
from tests.api_test_support import build_test_headers, create_api_test_context
from tests.test_model_deployment_package_archive import sample_package


def test_package_http_roundtrip_and_project_isolation(tmp_path):
    """上传入口不会登记部署；提交后回读停止实例，可再导出相同内容。"""
    context = create_api_test_context(tmp_path, database_name="transfer-api.db", enable_local_buffer_broker=False)
    service = ModelDeploymentTransferService(context.session_factory, context.dataset_storage)
    package = sample_package()
    package.deployment.runtime_configuration = serialize_deployment_runtime_configuration(build_default_runtime_configuration(runtime_backend="pytorch", device_name="cpu"))
    source = tmp_path / "weights.pt"
    source.write_bytes(b"model")
    archive = tmp_path / "sample.zip"
    write_package(archive, package, {"weights": source})
    headers = build_test_headers(scopes="models:read models:write")
    base = "/api/v1/projects/project-1/model-deployment-transfers"
    try:
        with context.client as client:
            with archive.open("rb") as handle:
                response = client.post(f"{base}/imports", headers=headers, files={"file": ("sample.zip", handle, "application/zip")})
            assert response.status_code == 202, response.text
            op_id = response.json()["operation_id"]
            assert "actor" not in response.json()
            service.run(op_id)
            analyzed = client.get(f"{base}/{op_id}", headers=headers).json()
            assert analyzed["state"] == "ready", analyzed
            wrong = client.post(f"{base}/imports/{op_id}/commit", headers=headers, json=ImportOptions(analysis_revision="old", idempotency_key="test").model_dump())
            assert wrong.status_code == 400, wrong.text
            response = client.post(f"{base}/imports/{op_id}/commit", headers=headers, json={"analysis_revision": analyzed["analysis_revision"], "idempotency_key": "test"})
            assert response.status_code == 202, response.text
            service.run(op_id)
            final = client.get(f"{base}/{op_id}", headers=headers).json()
            assert final["state"] == "completed", final
            assert final["deployment_id"] == "deployment-1"
            preview = client.get(f"{base}/deployment/deployment-1/deletion-preview", headers=headers)
            assert preview.status_code == 200, preview.text
            assert preview.json()["deleted_models"] == [{"kind": "model-version", "resource_id": "version-1"}]
            response = client.post(f"{base}/exports", headers=headers, json={"deployment_instance_id": "deployment-1"})
            assert response.status_code == 202
            export_id = response.json()["operation_id"]
            service.run(export_id)
            assert service.get(export_id)["state"] == "completed", service.get(export_id)
            response = client.get(f"{base}/exports/{export_id}/download", headers=headers)
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            assert response.content[:2] == b"PK"
            assert client.get(f"/api/v1/projects/project-other/model-deployment-transfers/{op_id}", headers=headers).status_code in {403, 404}
    finally:
        context.session_factory.engine.dispose()


def test_dismiss_failed_import_persists_and_preserves_receipt(tmp_path):
    """清除只影响列表；刷新、重建服务和重复请求不会使错误再次显示。"""
    context = create_api_test_context(tmp_path, database_name="dismiss-api.db", enable_local_buffer_broker=False)
    svc = ModelDeploymentTransferService(context.session_factory, context.dataset_storage)
    headers = build_test_headers(scopes="models:read models:write")
    base = "/api/v1/projects/project-1/model-deployment-transfers"
    try:
        with context.client as client:
            response = client.post(f"{base}/imports", headers=headers, files={"file": ("broken.zip", b"broken archive", "application/zip")})
            assert response.status_code == 202
            op_id = response.json()["operation_id"]
            assert client.post(f"{base}/{op_id}/dismiss", headers=headers).status_code == 400
            svc.run(op_id)
            before = svc.get(op_id)
            assert before["state"] == "failed"
            archive = context.dataset_storage.resolve(f"{svc.root(before)}/package.zip")
            assert any(row["operation_id"] == op_id for row in client.get(base, headers=headers).json())
            assert client.post(f"/api/v1/projects/project-other/model-deployment-transfers/{op_id}/dismiss", headers=headers).status_code in {403, 404}
            assert not svc.get(op_id).get("dismissed")
            for _ in range(2):
                assert client.post(f"{base}/{op_id}/dismiss", headers=headers).status_code == 204
                assert all(row["operation_id"] != op_id for row in client.get(base, headers=headers).json())
            restored = ModelDeploymentTransferService(context.session_factory, context.dataset_storage).get(op_id)
            assert restored["dismissed"] is True
            assert restored["state"] == "failed" and restored["error"] == before["error"]
            assert archive.read_bytes() == b"broken archive"
            assert client.get(f"{base}/{op_id}", headers=headers).status_code == 200
    finally:
        context.session_factory.engine.dispose()


def test_export_zip_state_and_deployment_references(tmp_path):
    """导出结果公开 zip_state，且只读引用接口准确返回引用该部署的 Workflow Runtime。"""
    import json
    from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppRuntime
    from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    from tests.api_test_support import issue_test_user_token

    context = create_api_test_context(tmp_path, database_name="ref-api.db", enable_local_buffer_broker=False)
    svc = ModelDeploymentTransferService(context.session_factory, context.dataset_storage)
    package = sample_package()
    package.deployment.runtime_configuration = serialize_deployment_runtime_configuration(build_default_runtime_configuration(runtime_backend="pytorch", device_name="cpu"))
    source = tmp_path / "weights.pt"
    source.write_bytes(b"model")
    archive = tmp_path / "sample.zip"
    write_package(archive, package, {"weights": source})
    headers = build_test_headers(scopes="models:read models:write")
    read_headers = build_test_headers(scopes="models:read")
    base = "/api/v1/projects/project-1/model-deployment-transfers"
    try:
        with context.client as client:
            with archive.open("rb") as handle:
                up = client.post(f"{base}/imports", headers=headers, files={"file": ("sample.zip", handle, "application/zip")})
            assert up.status_code == 202
            op_id = up.json()["operation_id"]
            svc.run(op_id)
            analyzed = client.get(f"{base}/{op_id}", headers=headers).json()
            client.post(f"{base}/imports/{op_id}/commit", headers=headers, json={"analysis_revision": analyzed["analysis_revision"], "idempotency_key": "ref-test"})
            svc.run(op_id)

            exp = client.post(f"{base}/exports", headers=headers, json={"deployment_instance_id": "deployment-1"})
            assert exp.status_code == 202
            export_id = exp.json()["operation_id"]
            svc.run(export_id)
            exported = client.get(f"{base}/{export_id}", headers=headers)
            assert exported.status_code == 200
            assert exported.json()["state"] == "completed"
            assert exported.json()["zip_state"] == "available"

            zip_path = context.dataset_storage.resolve(f"{svc.root(svc.get(export_id))}/package.zip")
            zip_path.unlink()
            missing = client.get(f"{base}/{export_id}", headers=headers)
            assert missing.status_code == 200
            assert missing.json()["state"] == "completed"
            assert missing.json()["zip_state"] == "missing"

            empty_refs = client.get(f"{base}/deployment/deployment-1/references", headers=read_headers)
            assert empty_refs.status_code == 200
            assert empty_refs.json() == {"items": [], "total": 0}

            manifest_key = "projects/project-1/apps/app-1/deps.json"
            manifest_path = context.dataset_storage.resolve(manifest_key)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps({"deployments": ["deployment-1"]}), encoding="utf-8")
            with context.session_factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                unit.workflow_runtime.save_workflow_app_runtime(
                    WorkflowAppRuntime(
                        workflow_runtime_id="wf-rt-1",
                        project_id="project-1",
                        application_id="app-1",
                        display_name="视觉检测产线",
                        application_snapshot_object_key="projects/project-1/apps/app-1/app.json",
                        template_snapshot_object_key="projects/project-1/apps/app-1/tpl.json",
                        desired_state="stopped",
                        observed_state="stopped",
                        metadata={"dependency_manifest_object_key": manifest_key},
                    )
                )
                unit.commit()

            refs = client.get(f"{base}/deployment/deployment-1/references", headers=read_headers)
            assert refs.status_code == 200, refs.text
            assert refs.json() == {
                "items": [{
                    "workflow_runtime_id": "wf-rt-1",
                    "application_id": "app-1",
                    "display_name": "视觉检测产线",
                    "desired_state": "stopped",
                    "observed_state": "stopped",
                    "relation": "direct",
                }],
                "total": 1,
            }
            assert client.get("/api/v1/projects/project-other/model-deployment-transfers/deployment/deployment-1/references", headers=read_headers).json() == {"items": [], "total": 0}
            scoped_token = issue_test_user_token(
                context.session_factory,
                username="project1-reader",
                scopes=("models:read",),
                project_ids=("project-1",),
            )
            assert client.get(
                "/api/v1/projects/project-other/model-deployment-transfers/deployment/deployment-1/references",
                headers={"Authorization": f"Bearer {scoped_token}"},
            ).status_code == 403
    finally:
        context.session_factory.engine.dispose()
