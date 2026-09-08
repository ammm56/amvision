"""数据集版本删除的真实导入、磁盘和依赖验收。"""

from pathlib import Path

import pytest

from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_dataset_import_api import (
    _build_coco_zip_bytes,
    _build_dataset_write_headers,
    _create_test_client,
    _load_dataset_objects,
    _run_import_worker_once,
)


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
            unit = SqlAlchemyUnitOfWork(factory.create_session())
            retained = unit.datasets.get_dataset_version(version.dataset_version_id)
            unit.close()
            assert (retained is not None) == (delete_kind == "blocked")
            assert storage.resolve(imported.version_path).exists() == (delete_kind == "blocked")
            assert storage.resolve(imported.package_path).exists() == (delete_kind == "blocked")
    finally:
        factory.engine.dispose()
