"""导出产物清理保留来源、报告，并复用可恢复删除。"""

from pathlib import Path

import pytest

from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.application.errors import PersistenceOperationError
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_dataset_export_api import (
    _create_test_client,
    _build_dataset_version,
    _seed_dataset_version,
    _run_export_worker_once,
    _build_dataset_read_headers,
    _build_dataset_write_headers,
    COCO_DETECTION_DATASET_FORMAT,
)


@pytest.mark.parametrize("fail_cleanup", [False, True])
def test_export_cleanup_retains_report_and_recovers(
    tmp_path: Path, monkeypatch, fail_cleanup
):
    """真实导出后模拟清理失败，恢复不能删除源版本或报告，也不能再下载旧 ZIP。"""
    client, factory, storage, queue = _create_test_client(tmp_path)
    version = _build_dataset_version(dataset_version_id="dataset-version-cleanup")
    _seed_dataset_version(
        session_factory=factory, dataset_storage=storage, dataset_version=version
    )
    read, write = _build_dataset_read_headers(), _build_dataset_write_headers()
    try:
        with client:
            submitted = client.post(
                "/api/v1/datasets/exports",
                headers=write,
                json={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "dataset_version_id": version.dataset_version_id,
                    "format_id": COCO_DETECTION_DATASET_FORMAT,
                },
            )
            assert submitted.status_code == 202, submitted.text
            ids = submitted.json()
            assert _run_export_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            url = f"/api/v1/datasets/exports/{ids['dataset_export_id']}"
            before = client.get(url, headers=read).json()
            assert client.get(url + "/files", headers=read).status_code == 200
            assert (
                client.get(
                    url + "/file-text", headers=read, params={"path": "../secret"}
                ).status_code
                == 400
            )
            service = ResourceDeletionService(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            operation = service.delete(
                kind="dataset-export-files",
                resource_id=ids["dataset_export_id"],
                project_id="project-1",
                asynchronous=True,
            )
            if fail_cleanup:
                original = storage.delete_tree

                def deny_staging(path):
                    """只拒绝物理暂存清理，模拟被占用文件。"""
                    if str(path).startswith("runtime/resource-deletion-staging/"):
                        raise PermissionError("test file is in use")
                    return original(path)

                monkeypatch.setattr(storage, "delete_tree", deny_staging)
                with pytest.raises(PersistenceOperationError, match="导出记录已保留"):
                    service.retry(operation)
                pending = client.get(
                    f"/api/v1/resource-deletions/{operation}", headers=write
                )
                assert pending.json()["state"] == "committed"
                monkeypatch.setattr(storage, "delete_tree", original)
            service.retry(operation)
            service.retry(operation)
            after = client.get(url, headers=read).json()
            assert after["metadata"]["files_cleaned_at"]
            assert after["sample_count"] == before["sample_count"]
            assert after["category_names"] == before["category_names"]
            assert not storage.resolve(before["export_path"]).exists()
            assert client.get(url + "/download", headers=read).status_code == 404
            assert client.get(url + "/files", headers=read).status_code == 404
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                assert (
                    unit.datasets.get_dataset_version(version.dataset_version_id)
                    is not None
                )
                assert unit.tasks.get_task(ids["task_id"]) is not None
            assert client.delete(url, headers=write).status_code == 204
            assert client.get(url, headers=read).status_code == 404
    finally:
        factory.engine.dispose()
