"""数据集导出 API 行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.contracts.datasets.exports.voc_detection_export import VOC_DETECTION_DATASET_FORMAT
from backend.service.api.app import create_app
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.datasets.dataset_export_queue_worker import DatasetExportQueueWorker


def test_create_dataset_export_and_get_completed_detail(tmp_path: Path) -> None:
    """验证可以通过 API 创建 DatasetExport 并读取完成后的详情。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_version = _build_dataset_version(dataset_version_id="dataset-version-api-1")
    _seed_dataset_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_version=dataset_version,
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/exports",
                headers=_build_dataset_write_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "dataset_version_id": "dataset-version-api-1",
                    "format_id": COCO_DETECTION_DATASET_FORMAT,
                    "include_test_split": False,
                },
            )

            assert create_response.status_code == 202
            create_payload = create_response.json()
            assert create_payload["dataset_export_id"]
            assert create_payload["task_id"]
            assert create_payload["status"] == "queued"
            assert create_payload["queue_task_id"]

            queued_detail_response = client.get(
                f"/api/v1/datasets/exports/{create_payload['dataset_export_id']}",
                headers=_build_dataset_read_headers(),
            )
            assert queued_detail_response.status_code == 200
            assert queued_detail_response.json()["status"] == "queued"
            assert queued_detail_response.json()["manifest_object_key"] is None

            assert _run_export_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            detail_response = client.get(
                f"/api/v1/datasets/exports/{create_payload['dataset_export_id']}",
                headers=_build_dataset_read_headers(),
            )
            list_response = client.get(
                "/api/v1/datasets/dataset-1/versions/dataset-version-api-1/exports",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["status"] == "completed"
        assert detail_payload["format_id"] == COCO_DETECTION_DATASET_FORMAT
        assert detail_payload["sample_count"] == 1
        assert detail_payload["category_names"] == ["bolt"]
        assert detail_payload["split_names"] == ["train"]
        assert detail_payload["manifest_object_key"].endswith("/manifest.json")
        assert dataset_storage.resolve(detail_payload["manifest_object_key"]).is_file()

        assert list_response.status_code == 200
        list_payload = list_response.json()
        assert len(list_payload) == 1
        assert list_payload[0]["dataset_export_id"] == create_payload["dataset_export_id"]
        assert list_payload[0]["status"] == "completed"
    finally:
        session_factory.engine.dispose()


def test_create_dataset_export_supports_voc_format(tmp_path: Path) -> None:
    """验证 API 可以创建 VOC detection DatasetExport。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_version = _build_dataset_version(dataset_version_id="dataset-version-api-voc")
    _seed_dataset_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_version=dataset_version,
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/exports",
                headers=_build_dataset_write_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "dataset_version_id": "dataset-version-api-voc",
                    "format_id": VOC_DETECTION_DATASET_FORMAT,
                },
            )

            assert create_response.status_code == 202
            create_payload = create_response.json()
            assert _run_export_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            detail_response = client.get(
                f"/api/v1/datasets/exports/{create_payload['dataset_export_id']}",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["status"] == "completed"
        assert detail_payload["format_id"] == VOC_DETECTION_DATASET_FORMAT
        assert dataset_storage.resolve(detail_payload["manifest_object_key"]).is_file()
        assert dataset_storage.resolve(f"{detail_payload['export_path']}/Annotations/sample-1.xml").is_file()
        assert dataset_storage.resolve(f"{detail_payload['export_path']}/ImageSets/Main/train.txt").is_file()
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定临时 SQLite、本地文件存储和队列的测试客户端。"""

    database_path = tmp_path / "amvision-export-api.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(
            enabled=False,
            max_concurrent_tasks=2,
            poll_interval_seconds=0.05,
        )
    )
    client = TestClient(
        create_app(
            settings=settings,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        )
    )
    return client, session_factory, dataset_storage, queue_backend


def _build_dataset_version(*, dataset_version_id: str) -> DatasetVersion:
    """构建 API 测试使用的最小 DatasetVersion。"""

    return DatasetVersion(
        dataset_version_id=dataset_version_id,
        dataset_id="dataset-1",
        project_id="project-1",
        categories=(DatasetCategory(category_id=0, name="bolt"),),
        samples=(
            DatasetSample(
                sample_id="sample-1",
                image_id=1,
                file_name="train-1.jpg",
                width=320,
                height=240,
                split="train",
                annotations=(
                    DetectionAnnotation(
                        annotation_id="ann-1",
                        category_id=0,
                        bbox_xywh=(1.0, 2.0, 3.0, 4.0),
                    ),
                ),
            ),
        ),
    )


def _seed_dataset_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_version: DatasetVersion,
) -> None:
    """把测试用 DatasetVersion 及其图片文件写入数据库和本地存储。"""

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    for sample in dataset_version.samples:
        image_object_key = str(
            sample.metadata.get("image_object_key") or f"images/{sample.split}/{sample.file_name}"
        ).lstrip("/")
        dataset_storage.write_bytes(
            (
                f"projects/{dataset_version.project_id}/datasets/{dataset_version.dataset_id}/versions/"
                f"{dataset_version.dataset_version_id}/{image_object_key}"
            ),
            b"fake-image",
        )


def _run_export_worker_once(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> bool:
    """执行一次 DatasetExport 队列 worker。"""

    worker = DatasetExportQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-export-worker",
    )
    return worker.run_once()


def _build_dataset_write_headers() -> dict[str, str]:
    """构建具备 datasets:write scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "datasets:write",
    }


def _build_dataset_read_headers() -> dict[str, str]:
    """构建具备 datasets:read scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "datasets:read",
    }