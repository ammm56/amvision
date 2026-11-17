"""数据集版本删除的真实导入、磁盘和依赖验收。"""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.dataset_import_orm import DatasetImportRecord
from backend.service.infrastructure.persistence.dataset_orm import (
    DatasetAnnotationRecord,
    DatasetCategoryRecord,
    DatasetSampleRecord,
)
from backend.workers.resource_cleanup import ResourceCleanupWorker
from tests.test_dataset_import_api import (
    _build_coco_zip_bytes,
    _build_dataset_write_headers,
    _create_test_client,
    _load_dataset_objects,
    _run_import_worker_once,
)
from tests.test_dataset_export_api import COCO_DETECTION_DATASET_FORMAT, _run_export_worker_once


@pytest.mark.parametrize("delete_kind", ["dataset", "version", "blocked"])
def test_delete_dataset_resources_after_real_import(tmp_path: Path, delete_kind: str) -> None:
    """删除范围覆盖真实图片和标注，并在训练引用存在时保持原数据。"""
    client, factory, storage, queue = _create_test_client(tmp_path)
    headers = _build_dataset_write_headers()
    try:
        with client:
            response = client.post("/api/v1/datasets/imports", headers=headers, data={"project_id": "project-1", "dataset_id": "dataset-delete", "task_type": "detection"}, files={"package": ("dataset.zip", _build_coco_zip_bytes(), "application/zip")})
            assert response.status_code == 202, response.text
            assert _run_import_worker_once(session_factory=factory, dataset_storage=storage, queue_backend=queue)
            imported, version = _load_dataset_objects(session_factory=factory, dataset_import_id=response.json()["dataset_import_id"])
            assert imported is not None and version is not None
            with factory.create_session() as session:
                sample_ids = list(session.scalars(select(DatasetSampleRecord.sample_id).where(DatasetSampleRecord.dataset_version_id == version.dataset_version_id)))
                annotation_ids = list(session.scalars(select(DatasetAnnotationRecord.annotation_id).where(DatasetAnnotationRecord.sample_id.in_(sample_ids))))
                category_count = session.scalar(select(func.count()).select_from(DatasetCategoryRecord).where(DatasetCategoryRecord.dataset_version_id == version.dataset_version_id))
                assert sample_ids and annotation_ids and category_count
            sibling = "projects/project-1/datasets/dataset-preserved/versions/v1/keep.bin"
            storage.write_bytes(sibling, b"preserve")
            if delete_kind == "blocked":
                unit = SqlAlchemyUnitOfWork(factory.create_session())
                unit.tasks.save_task(TaskRecord(task_id="dependent-training", task_kind="detection-training", project_id="project-1", state="failed", task_spec={"dataset_version_id": version.dataset_version_id}))
                unit.commit()
                unit.close()
            url = f"/api/v1/datasets/versions/{version.dataset_version_id}"
            if delete_kind == "dataset":
                url = "/api/v1/datasets/dataset-delete?project_id=project-1"
            deleted = client.delete(url, headers=headers)
            assert deleted.status_code == (409 if delete_kind == "blocked" else 204), deleted.text
            catalog = client.get("/api/v1/datasets/catalog/dataset-delete", headers=headers, params={"project_id": "project-1"})
            assert catalog.status_code == (404 if delete_kind == "dataset" else 200)
            unit = SqlAlchemyUnitOfWork(factory.create_session())
            retained = unit.datasets.get_dataset_version(version.dataset_version_id)
            unit.close()
            assert (retained is not None) == (delete_kind == "blocked")
            assert storage.resolve(imported.version_path).exists() == (delete_kind == "blocked")
            assert storage.resolve(imported.package_path).exists() == (delete_kind == "blocked")
            with factory.create_session() as session:
                assert session.scalar(select(func.count()).select_from(DatasetSampleRecord).where(DatasetSampleRecord.sample_id.in_(sample_ids))) == (len(sample_ids) if delete_kind == "blocked" else 0)
                assert session.scalar(select(func.count()).select_from(DatasetAnnotationRecord).where(DatasetAnnotationRecord.annotation_id.in_(annotation_ids))) == (len(annotation_ids) if delete_kind == "blocked" else 0)
                assert session.scalar(select(func.count()).select_from(DatasetCategoryRecord).where(DatasetCategoryRecord.dataset_version_id == version.dataset_version_id)) == (category_count if delete_kind == "blocked" else 0)
                assert (session.get(DatasetImportRecord, imported.dataset_import_id) is not None) == (delete_kind == "blocked")
            assert storage.resolve(sibling).read_bytes() == b"preserve"
            if delete_kind == "dataset":
                assert not storage.resolve("projects/project-1/datasets/dataset-delete").exists()
    finally:
        factory.engine.dispose()


def test_delete_dataset_with_import_and_export_leaves_no_owned_data(tmp_path: Path) -> None:
    """真实导入与导出后异步删除，核对任务、业务记录和文件均被清理。"""
    client, factory, storage, queue = _create_test_client(tmp_path)
    headers = _build_dataset_write_headers()
    try:
        with client:
            imported = client.post(
                "/api/v1/datasets/imports", headers=headers,
                data={"project_id": "project-1", "dataset_id": "dataset-with-export", "task_type": "detection"},
                files={"package": ("dataset.zip", _build_coco_zip_bytes(), "application/zip")},
            )
            assert imported.status_code == 202, imported.text
            assert _run_import_worker_once(session_factory=factory, dataset_storage=storage, queue_backend=queue)
            record, version = _load_dataset_objects(session_factory=factory, dataset_import_id=imported.json()["dataset_import_id"])
            assert record is not None and version is not None
            exported = client.post(
                "/api/v1/datasets/exports", headers=headers,
                json={"project_id": "project-1", "dataset_id": "dataset-with-export", "dataset_version_id": version.dataset_version_id, "format_id": COCO_DETECTION_DATASET_FORMAT},
            )
            assert exported.status_code == 202, exported.text
            assert _run_export_worker_once(session_factory=factory, dataset_storage=storage, queue_backend=queue)
            export_id = exported.json()["dataset_export_id"]
            export_task_id = exported.json()["task_id"]
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                export_record = unit.dataset_exports.get_dataset_export(export_id)
                assert export_record is not None and export_record.export_path
                assert storage.resolve(export_record.export_path).exists()
                assert unit.tasks.get_task(export_task_id) is not None
            deleted = client.post(
                "/api/v1/resource-deletions", headers=headers,
                json={"kind": "dataset", "resource_id": "dataset-with-export", "project_id": "project-1"},
            )
            assert deleted.status_code == 202, deleted.text
            worker = ResourceCleanupWorker(session_factory=factory, dataset_storage=storage, queue_backend=queue, worker_id="cleanup-test")
            worker.run_once()
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                assert unit.datasets.get_dataset_version(version.dataset_version_id) is None
                assert unit.dataset_exports.get_dataset_export(export_id) is None
                assert unit.tasks.get_task(export_task_id) is None
                assert session.get(DatasetImportRecord, record.dataset_import_id) is None
                assert unit.resource_deletions.list_pending() == []
            assert not storage.resolve("projects/project-1/datasets/dataset-with-export").exists()
            assert not storage.resolve(export_record.export_path).exists()
            staging = storage.resolve("runtime/resource-deletion-staging")
            assert not staging.exists() or not any(staging.iterdir())
    finally:
        factory.engine.dispose()


def test_delete_dataset_after_last_version_is_removed(tmp_path: Path) -> None:
    """最后一个版本删除后，仍可通过统一删除接口删除数据集本身。"""
    client, factory, storage, queue = _create_test_client(tmp_path)
    headers = _build_dataset_write_headers()
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=headers,
                data={"project_id": "project-1", "dataset_id": "dataset-empty-delete", "task_type": "detection"},
                files={"package": ("dataset.zip", _build_coco_zip_bytes(), "application/zip")},
            )
            assert response.status_code == 202, response.text
            assert _run_import_worker_once(session_factory=factory, dataset_storage=storage, queue_backend=queue)
            _, version = _load_dataset_objects(session_factory=factory, dataset_import_id=response.json()["dataset_import_id"])
            assert version is not None
            removed_version = client.delete(f"/api/v1/datasets/versions/{version.dataset_version_id}", headers=headers)
            assert removed_version.status_code == 204, removed_version.text
            catalog_url = "/api/v1/datasets/catalog/dataset-empty-delete"
            assert client.get(catalog_url, headers=headers, params={"project_id": "project-1"}).status_code == 200
            removed_dataset = client.post(
                "/api/v1/resource-deletions",
                headers=headers,
                json={"kind": "dataset", "resource_id": "dataset-empty-delete", "project_id": "project-1"},
            )
            assert removed_dataset.status_code == 202, removed_dataset.text
            assert removed_dataset.json()["state"] in {"committed", "completed"}
            assert client.get(catalog_url, headers=headers, params={"project_id": "project-1"}).status_code == 404
            worker = ResourceCleanupWorker(session_factory=factory, dataset_storage=storage, queue_backend=queue, worker_id="cleanup-test")
            worker.run_once()
            with factory.create_session() as session:
                assert SqlAlchemyUnitOfWork(session).resource_deletions.list_pending() == []
            assert not storage.resolve("projects/project-1/datasets/dataset-empty-delete").exists()
            staging = storage.resolve("runtime/resource-deletion-staging")
            assert not staging.exists() or not any(staging.iterdir())
    finally:
        factory.engine.dispose()
