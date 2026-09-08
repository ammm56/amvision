"""同实例重复导出、文件变化和到期清理的回归。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.contracts.deployments.model_package import ImportOptions
from backend.service.application.deployments.transfer_service import ModelDeploymentTransferService
from backend.service.infrastructure.persistence.model_transfer_repository import ModelTransferRecord
from tests.api_test_support import create_test_runtime
from tests.test_model_deployment_package_import import upload_fixture


@pytest.fixture
def service(tmp_path):
    """登记一个可真实重导出的独立部署。"""
    factory, storage, _ = create_test_runtime(tmp_path, database_name="reuse.db")
    svc = ModelDeploymentTransferService(factory, storage)
    imported = upload_fixture(tmp_path, svc)
    svc.commit(imported["operation_id"], ImportOptions(analysis_revision=imported["analysis_revision"], idempotency_key="seed"))
    svc.run(imported["operation_id"])
    assert svc.get(imported["operation_id"])["state"] == "completed"
    yield svc
    factory.engine.dispose()


def export(service):
    """完成一次 Worker 导出并返回操作和文件。"""
    op = service.create("project-1", "export", deployment_id="deployment-1")
    service.run(op["operation_id"])
    result = service.get(op["operation_id"])
    assert result["state"] == "completed", result
    return result, service.storage.resolve(f"{service.root(result)}/package.zip")


def test_repeated_and_concurrent_exports_share_operation_and_unchanged_zip(service):
    """并发登记只有一个操作；再次导出不改变 ZIP 字节或写入时间。"""
    with ThreadPoolExecutor(max_workers=4) as pool:
        operations = list(pool.map(lambda _: service.create("project-1", "export", deployment_id="deployment-1"), range(8)))
    assert len({op["operation_id"] for op in operations}) == 1
    first, path = export(service)
    original, modified = path.read_bytes(), path.stat().st_mtime_ns
    second, repeated = export(service)
    assert first["operation_id"] == second["operation_id"]
    assert repeated == path and path.read_bytes() == original
    assert path.stat().st_mtime_ns == modified
    assert len([op for op in service.list() if op["direction"] == "export"]) == 1


def test_configuration_change_replaces_only_current_zip(service):
    """名称等可传递配置变化后必须更新同一 ZIP。"""
    first, path = export(service)
    with service.unit() as unit:
        instance = unit.deployments.get_deployment_instance("deployment-1")
        unit.deployments.save_deployment_instance(replace(instance, display_name="new name"))
        unit.commit()
    second, repeated = export(service)
    assert repeated == path
    assert first["archive_sha256"] != second["archive_sha256"]
    assert second["display_name"] == "new name"


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_damaged_zip_is_regenerated(service, missing):
    """缓存缺失或损坏不能继续返回成功的旧下载。"""
    first, path = export(service)
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"damaged")
    second, repeated = export(service)
    assert second["operation_id"] == first["operation_id"]
    assert repeated == path and path.read_bytes().startswith(b"PK")


def test_expired_export_reuses_receipt_and_rebuilds_file(service):
    """短期 ZIP 到期后重新导出仍复用回执，不额外增加目录。"""
    first, path = export(service)
    with service.unit() as unit:
        row = unit.session.get(ModelTransferRecord, first["operation_id"])
        row.updated_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        unit.commit()
    service.maintenance()
    assert not path.exists()
    second, path = export(service)
    assert second["operation_id"] == first["operation_id"] and path.is_file()


def test_source_file_change_updates_content_fingerprint(service):
    """相同文件路径的新内容不会误用旧 ZIP。"""
    first, path = export(service)
    # 根据登记文件定位夹具，避免测试依赖目录拼写。
    with service.unit() as unit:
        file = unit.model_files.list_model_files(model_version_id="version-1")[0]
        source = service.storage.resolve_deletion_path(file.storage_uri)
    source.write_bytes(b"model with updated weights")
    second, repeated = export(service)
    assert repeated == path
    assert second["export_fingerprint"] != first["export_fingerprint"]


def test_old_duplicate_exports_are_retired_after_current_package_is_ready(service):
    """旧实现的重复包会清理，保留短期回执并明确过期。"""
    first, old_path = export(service)
    newer = service._create("project-1", "export", deployment_id="deployment-1", actor=None)
    service.run(newer["operation_id"])
    assert service.get(newer["operation_id"])["state"] == "completed"
    assert service.get(first["operation_id"])["state"] == "expired"
    assert not old_path.exists()
