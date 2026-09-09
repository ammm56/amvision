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
