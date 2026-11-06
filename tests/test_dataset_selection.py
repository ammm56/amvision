"""样本选择导出及待执行任务取消的端到端契约。"""

from dataclasses import replace
import pytest
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.application.errors import InvalidRequestError
from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
)
from tests.test_dataset_export_api import (
    _create_test_client,
    _build_dataset_version,
    _seed_dataset_version,
    _run_export_worker_once,
    _build_dataset_read_headers,
    _build_dataset_write_headers,
)


@pytest.mark.parametrize(
    "selection",
    [
        {"mode": "ids", "sample_ids": ["sample-test"]},
        {"mode": "filter", "split": "test", "category_id": 0},
    ],
)
def test_selected_export_counts_and_original_remains(tmp_path, selection):
    """筛选汇总、worker 实际导出及报告数量一致，来源不被修改。"""
    client, factory, storage, queue = _create_test_client(tmp_path)
    version = _build_dataset_version(dataset_version_id="version-selection")
    sample = replace(
        version.samples[0],
        sample_id="sample-test",
        image_id=2,
        split="test",
        file_name="test.jpg",
        annotations=(
            replace(version.samples[0].annotations[0], annotation_id="ann-test"),
        ),
    )
    version = replace(version, samples=(*version.samples, sample))
    _seed_dataset_version(
        session_factory=factory, dataset_storage=storage, dataset_version=version
    )
    base = "/api/v1/datasets/dataset-1/versions/version-selection"
    payload = {
        "project_id": "project-1",
        "dataset_id": "dataset-1",
        "dataset_version_id": "version-selection",
        "format_id": COCO_DETECTION_DATASET_FORMAT,
        "selection": selection,
    }
    try:
        with client:
            summary = client.post(
                base + "/selection-summary",
                headers=_build_dataset_read_headers(),
                json=selection,
            )
            assert summary.status_code == 200, summary.text
            assert summary.json() == {"sample_count": 1, "split_counts": {"test": 1}}
            empty = client.post(
                "/api/v1/datasets/exports",
                headers=_build_dataset_write_headers(),
                json={**payload, "include_test_split": False},
            )
            assert empty.status_code == 400, empty.text
            submitted = client.post(
                "/api/v1/datasets/exports",
                headers=_build_dataset_write_headers(),
                json=payload,
            )
            assert submitted.status_code == 202, submitted.text
            assert _run_export_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            result = client.get(
                "/api/v1/datasets/exports/" + submitted.json()["dataset_export_id"],
                headers=_build_dataset_read_headers(),
            ).json()
            assert result["status"] == "completed", result
            assert result["sample_count"] == 1
            assert result["metadata"]["split_counts"] == {"test": 1}
            assert (
                client.get(
                    base + "/workspace", headers=_build_dataset_read_headers()
                ).json()["sample_count"]
                == 2
            )
            bad = client.post(
                base + "/selection-summary",
                headers=_build_dataset_read_headers(),
                json={"mode": "ids", "sample_ids": ["foreign"]},
            )
            assert bad.status_code == 400
    finally:
        factory.engine.dispose()


def test_cancel_waiting_export_updates_record_and_cannot_execute(tmp_path):
    """取消同一事务更新 Task 和记录，不能留一个永远等待的导出。"""
    client, factory, storage, queue = _create_test_client(tmp_path)
    version = _build_dataset_version(dataset_version_id="version-cancel")
    _seed_dataset_version(
        session_factory=factory, dataset_storage=storage, dataset_version=version
    )
    try:
        with client:
            submitted = client.post(
                "/api/v1/datasets/exports",
                headers=_build_dataset_write_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "dataset_version_id": "version-cancel",
                    "format_id": COCO_DETECTION_DATASET_FORMAT,
                },
            ).json()
            SqlAlchemyTaskService(factory).cancel_task(submitted["task_id"])
            result = client.get(
                "/api/v1/datasets/exports/" + submitted["dataset_export_id"],
                headers=_build_dataset_read_headers(),
            ).json()
            assert result["status"] == "cancelled"
            from backend.service.application.datasets.exports.task_service import (
                SqlAlchemyDatasetExportTaskService,
            )

            service = SqlAlchemyDatasetExportTaskService(
                session_factory=factory, dataset_storage=storage
            )
            with pytest.raises(InvalidRequestError):
                service.process_export_task(submitted["dataset_export_id"])
            # outbox 正常投递后，claim 会消费已取消消息而不执行导出。
            _run_export_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            result = client.get(
                "/api/v1/datasets/exports/" + submitted["dataset_export_id"],
                headers=_build_dataset_read_headers(),
            ).json()
            assert result["status"] == "cancelled"
            assert not result.get("package_path")
            assert (
                client.delete(
                    "/api/v1/datasets/exports/" + submitted["dataset_export_id"],
                    headers=_build_dataset_write_headers(),
                ).status_code
                == 204
            )
    finally:
        factory.engine.dispose()


def test_cancel_waiting_import_preserves_status_and_is_deletable(tmp_path):
    """等待导入取消后记录和 Task 一致；可删除取消记录而非永久阻塞。"""
    from tests.test_dataset_import_api import (
        _build_coco_zip_bytes,
        _create_test_client as import_client,
        _run_import_worker_once,
    )

    client, factory, storage, queue = import_client(tmp_path)
    try:
        with client:
            submitted = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "cancelled-import",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco.zip", _build_coco_zip_bytes(), "application/zip")
                },
            ).json()
            SqlAlchemyTaskService(factory).cancel_task(submitted["task_id"])
            record = client.get(
                "/api/v1/datasets/imports/" + submitted["dataset_import_id"],
                headers=_build_dataset_read_headers(),
            ).json()
            assert record["status"] == "cancelled"
            _run_import_worker_once(
                session_factory=factory, dataset_storage=storage, queue_backend=queue
            )
            record = client.get(
                "/api/v1/datasets/imports/" + submitted["dataset_import_id"],
                headers=_build_dataset_read_headers(),
            ).json()
            assert record["status"] == "cancelled"
            assert record["dataset_version_id"] is None
            assert (
                client.delete(
                    "/api/v1/datasets/imports/" + submitted["dataset_import_id"],
                    headers=_build_dataset_write_headers(),
                ).status_code
                == 204
            )
    finally:
        factory.engine.dispose()
