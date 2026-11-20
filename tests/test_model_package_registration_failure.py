"""验证独立模型包登记失败、回滚和原 ZIP 复检。"""

from errno import ENOSPC
from pathlib import Path

from backend.contracts.models.model_package import ModelPackage
from backend.service.application.deployments import transfer_service
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.infrastructure.object_store.model_package_archive import file_digest, write_package
from tests.api_test_support import build_test_headers, create_api_test_context
from tests.test_model_deployment_package_archive import sample_package


def exercise_registration_failure(tmp_path, monkeypatch, checkpoint: Path | None = None):
    """走真实 API 和登记事务；可用已有检查点核对错误页。"""
    if checkpoint is None:
        import torch

        checkpoint = tmp_path / "source.pt"
        torch.save({"weight": torch.zeros(1)}, checkpoint)
    digest, size = file_digest(checkpoint)
    example = sample_package()
    archive = tmp_path / "model.zip"
    package = ModelPackage(
        package_id=example.package_id, source_version=example.source_version, created_at=example.created_at,
        model=example.model, model_version=example.model_version.model_copy(update={"metadata": {"category_names": ["good", "bad"]}}),
        files=[example.files[0].model_copy(update={"sha256": digest, "byte_size": size})],
    )
    write_package(archive, package, {"weights": checkpoint})
    ctx = create_api_test_context(tmp_path, database_name="package.db", enable_local_buffer_broker=False, enable_queue_outbox_dispatcher=False)
    svc = ModelDeploymentTransferService(ctx.session_factory, ctx.dataset_storage)
    project = "/api/v1/projects/project-1/model-packages"
    headers = build_test_headers(scopes="models:read models:write")
    try:
        with ctx.client as client:
            def read(operation_id):
                response = client.get(f"{project}/{operation_id}", headers=headers)
                assert response.status_code == 200, response.text
                return response.json()

            def upload():
                with archive.open("rb") as source:
                    response = client.post(f"{project}/imports", headers=headers, files={"file": ("model.zip", source, "application/zip")})
                assert response.status_code == 202, response.text
                operation_id = response.json()["operation_id"]
                svc.run(operation_id)
                return read(operation_id)

            def analyze(row, options):
                return client.post(f"{project}/imports/{row['operation_id']}/analyze", headers=headers, json=options)

            def commit(row):
                response = client.post(f"{project}/imports/{row['operation_id']}/commit", headers=headers, json={"analysis_revision": row["analysis_revision"], "idempotency_key": "test-registration"})
                assert response.status_code == 202, response.text
                svc.run(row["operation_id"])
                return read(row["operation_id"])

            existing = commit(upload())
            assert existing["state"] == "completed", existing
            result = existing["result"]
            prefix = "projects/project-1/models/imported/versions"
            previous_dir = ctx.dataset_storage.resolve(f"{prefix}/{result['model_version_id']}")
            assert file_digest(previous_dir / "files" / "best.pt") == (digest, size)
            row = upload()
            options = {"target_model_id": result["model_id"], "description": "复检时保留说明"}
            assert analyze(row, options).status_code == 202
            svc.run(row["operation_id"])
            ready = read(row["operation_id"])
            assert ready["state"] == "ready", ready
            next_id = svc.get(row["operation_id"])["plan"]["mapping"]["version"]
            register = transfer_service.register_model_package

            def fail_after_write(*args):
                register(*args)
                raise OSError(ENOSPC, "internal-marker")

            with monkeypatch.context() as isolated:
                isolated.setattr(transfer_service, "register_model_package", fail_after_write)
                failed = commit(ready)
            assert failed["state"] == "failed", failed
            assert failed["failure_stage"] == "registration"
            assert failed["failure_code"] == "storage_full"
            assert failed["can_recheck"] is True
            assert failed["import_description"] == options["description"]
            assert failed["plan"]["name"] == example.model.model_name
            assert "error" not in failed
            assert not ctx.dataset_storage.resolve(f"{prefix}/{next_id}").exists()
            assert file_digest(previous_dir / "files" / "best.pt") == (digest, size)
            with svc.unit() as unit:
                assert unit.models.get_model_version(result["model_version_id"]) is not None
                assert unit.models.get_model_version(next_id) is None
            analysis_started = analyze(failed, options)
            assert analysis_started.status_code == 202
            svc.run(row["operation_id"])
            checked = read(row["operation_id"])
            assert checked["state"] == "ready"
            assert "failure_stage" not in checked
            with monkeypatch.context() as isolated:
                isolated.setattr(transfer_service, "register_model_package", fail_after_write)
                assert commit(checked)["state"] == "failed"
            ctx.dataset_storage.resolve(f"{svc.root(svc.get(row['operation_id']))}/package.zip").unlink()
            expired = read(row["operation_id"])
            assert expired["can_recheck"] is False
            result = analyze(expired, options)
            assert result.status_code == 400 and "请重新上传" in result.text, result.text
            return failed, analysis_started.json(), checked, expired
    finally:
        ctx.session_factory.engine.dispose()


def test_registration_failure_rolls_back_and_rechecks(tmp_path, monkeypatch):
    """登记失败不破坏已有版本，重新检查依赖仍可用的 ZIP。"""
    exercise_registration_failure(tmp_path, monkeypatch)
