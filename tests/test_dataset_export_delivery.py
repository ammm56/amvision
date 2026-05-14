"""DatasetExport delivery service 行为测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.application.datasets.dataset_export import DatasetExportRequest
from backend.service.application.datasets.dataset_export_delivery import (
    SqlAlchemyDatasetExportDeliveryService,
)
from backend.service.domain.datasets.dataset_version import DatasetCategory, DatasetSample, DatasetVersion
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_dataset_export import _create_export_task_service_with_storage, _run_export_worker_once


def test_package_export_can_write_temporary_package_without_persisting_download_metadata(
    tmp_path: Path,
) -> None:
    """验证临时 package 输出路径不会把下载 zip 元数据写回 DatasetExport。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-delivery-1",
        dataset_id="dataset-1",
        project_id="project-1",
        categories=(DatasetCategory(category_id=0, name="bolt"),),
        samples=(
            DatasetSample(
                sample_id="sample-1",
                image_id=1,
                file_name="train-1.jpg",
                width=640,
                height=480,
                split="train",
            ),
        ),
    )
    export_task_service, session_factory, dataset_storage, queue_backend = _create_export_task_service_with_storage(
        tmp_path,
        dataset_version,
    )

    try:
        submission = export_task_service.submit_export_task(
            DatasetExportRequest(
                project_id="project-1",
                dataset_id="dataset-1",
                dataset_version_id="dataset-version-delivery-1",
                format_id=COCO_DETECTION_DATASET_FORMAT,
            ),
            created_by="workflow-user",
        )
        assert _run_export_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        delivery_service = SqlAlchemyDatasetExportDeliveryService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )
        package = delivery_service.package_export(
            submission.dataset_export_id,
            package_object_key="workflows/runtime/run-1/package/dataset-export-1.zip",
            persist_package_metadata=False,
        )

        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            dataset_export = unit_of_work.dataset_exports.get_dataset_export(submission.dataset_export_id)
        finally:
            unit_of_work.close()

        assert dataset_export is not None
        assert package.package_object_key == "workflows/runtime/run-1/package/dataset-export-1.zip"
        assert package.package_file_name == f"dataset-1-{COCO_DETECTION_DATASET_FORMAT}-{submission.dataset_export_id}.zip"
        assert dataset_storage.resolve(package.package_object_key).is_file()
        assert dataset_export.metadata.get("package_object_key") is None
        assert dataset_export.metadata.get("package_file_name") is None
        assert dataset_export.metadata.get("package_size") is None
        assert dataset_export.metadata.get("packaged_at") is None
    finally:
        session_factory.engine.dispose()