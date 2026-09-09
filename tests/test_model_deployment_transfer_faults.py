"""导入提交、取消、到期和范围变化的故障回归。"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.contracts.deployments.model_package import ImportOptions
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.application.errors import InvalidRequestError, ResourceInUseError
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.infrastructure.persistence.model_transfer_repository import ModelTransferRecord
from tests.api_test_support import create_test_runtime
from tests.test_model_deployment_package_import import upload_fixture


def test_registration_failure_rolls_back_owned_files_and_models(tmp_path, monkeypatch):
    """文件已经移动后登记失败，必须回收新文件且没有半套模型。"""
    factory, storage, _ = create_test_runtime(tmp_path, database_name="rollback.db")
    svc = ModelDeploymentTransferService(factory, storage)
    try:
        op = upload_fixture(tmp_path, svc)
        svc.commit(op["operation_id"], ImportOptions(analysis_revision=op["analysis_revision"], idempotency_key="failure"))
        def fail(*args):
            raise OSError("injected storage failure")
        monkeypatch.setattr("backend.service.application.deployments.transfer_service.register_import", fail)
        svc.run(op["operation_id"])
        result = svc.get(op["operation_id"])
        assert result["state"] == "failed", result
        assert not storage.resolve("projects/project-1/models/imported/versions/version-1").exists()
        with svc.unit() as unit:
            assert unit.models.get_model_version("version-1") is None
    finally:
        factory.engine.dispose()


def test_cancel_prevents_commit_and_expiry_cleans_upload(tmp_path):
    """取消和提交之间不能丢取消；短期文件确实到期删除。"""
    factory, storage, _ = create_test_runtime(tmp_path, database_name="cancel-expire.db")
    svc = ModelDeploymentTransferService(factory, storage)
    try:
        op = upload_fixture(tmp_path, svc)
        svc.cancel(op["operation_id"])
        with pytest.raises(InvalidRequestError):
            svc.commit(op["operation_id"], ImportOptions(analysis_revision=op["analysis_revision"], idempotency_key="cancel"))
        svc.run(op["operation_id"])
        assert svc.get(op["operation_id"])["state"] == "cancelled"
        assert not storage.resolve(f"{svc.root(op)}/package.zip").exists()
        with svc.unit() as unit:
            row = unit.session.get(ModelTransferRecord, op["operation_id"])
            row.updated_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
            unit.commit()
        svc.maintenance()
        with svc.unit() as unit:
            assert unit.model_transfers.get(op["operation_id"]) is None
    finally:
        factory.engine.dispose()


def test_deletion_preview_revision_rejects_expanded_scope(tmp_path):
    """预览时共享的资产变成独占后，旧确认不能扩大删除范围。"""
    factory, storage, queue = create_test_runtime(tmp_path, database_name="revision.db")
    svc = ModelDeploymentTransferService(factory, storage)
    delete = ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue)
    try:
        op = upload_fixture(tmp_path, svc)
        svc.commit(op["operation_id"], ImportOptions(analysis_revision=op["analysis_revision"], idempotency_key="revision"))
        svc.run(op["operation_id"])
        with svc.unit() as unit:
            instance = unit.deployments.get_deployment_instance("deployment-1")
            unit.deployments.save_deployment_instance(replace(instance, deployment_instance_id="deployment-2"))
            unit.commit()
        preview = delete.preview(kind="deployment", resource_id="deployment-1", project_id="project-1")
        assert not preview["deleted_models"]
        delete.delete(kind="deployment", resource_id="deployment-2", project_id="project-1")
        with pytest.raises(ResourceInUseError, match="删除范围已变化"):
            delete.delete(kind="deployment", resource_id="deployment-1", project_id="project-1", expected_revision=preview["revision"])
        with svc.unit() as unit:
            assert unit.models.get_model_version("version-1") is not None
    finally:
        factory.engine.dispose()


def test_unknown_runtime_setting_is_reported_and_can_be_corrected(tmp_path):
    """旧或误拼配置不能静默丢弃，修正后仍可继续分析。"""
    factory, storage, _ = create_test_runtime(tmp_path, database_name="settings.db")
    svc = ModelDeploymentTransferService(factory, storage)
    try:
        op = upload_fixture(tmp_path, svc)
        configuration = op["plan"]["runtime_configuration"]
        configuration["execution"]["misspelled_option"] = True
        svc.analyze(op["operation_id"], ImportOptions(runtime_configuration=configuration))
        svc.run(op["operation_id"])
        invalid = svc.get(op["operation_id"])
        assert invalid["state"] == "needs_attention"
        assert invalid["plan"]["issues"][0]["code"] == "invalid_runtime_configuration"
        del configuration["execution"]["misspelled_option"]
        svc.analyze(op["operation_id"], ImportOptions(runtime_configuration=configuration))
        svc.run(op["operation_id"])
        assert svc.get(op["operation_id"])["state"] == "ready"
    finally:
        factory.engine.dispose()


@pytest.mark.parametrize("state,values", [
    ("uploading", {}), ("pending_analysis", {}), ("analyzing", {}),
    ("ready", {}), ("needs_attention", {}), ("pending_import", {}),
    ("importing", {}), ("completed", {}),
    ("failed", {"prepared_paths": ["pending-recovery"]}),
    ("failed", {"cancel_requested": True}),
])
def test_dismiss_rejects_active_or_recovering_imports(tmp_path, state, values):
    """不能通过清除按钮隐藏活动、待处理或需要回滚恢复的操作。"""
    factory, storage, _ = create_test_runtime(tmp_path, database_name="dismiss-guard.db")
    svc = ModelDeploymentTransferService(factory, storage)
    try:
        op = svc.create("project-1", "import")
        svc.update(op["operation_id"], state, **values)
        with pytest.raises(InvalidRequestError, match="只能清除"):
            svc.dismiss(op["operation_id"])
        assert not svc.get(op["operation_id"]).get("dismissed")
    finally:
        factory.engine.dispose()


def test_dismissed_import_cannot_be_reanalyzed(tmp_path):
    """其他旧页面不能重新执行已经清除的失败导入。"""
    factory, storage, _ = create_test_runtime(tmp_path, database_name="dismiss-analysis.db")
    svc = ModelDeploymentTransferService(factory, storage)
    try:
        op = upload_fixture(tmp_path, svc)
        svc.update(op["operation_id"], "failed", error="test failure")
        svc.dismiss(op["operation_id"])
        with pytest.raises(InvalidRequestError):
            svc.analyze(op["operation_id"], ImportOptions())
        assert svc.get(op["operation_id"])["state"] == "failed"
    finally:
        factory.engine.dispose()
