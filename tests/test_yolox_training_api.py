"""YOLOX 训练任务创建 API 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.api.app import create_app
from backend.service.application.models.yolox_training_service import YOLOX_TRAINING_QUEUE_NAME
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.training.yolox_training_queue_worker import YoloXTrainingQueueWorker


def test_create_yolox_training_task_accepts_dataset_export_id(tmp_path: Path) -> None:
    """验证训练创建接口可以直接接收 dataset_export_id。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-1/manifest.json"
        ),
    )
    try:
        with client:
            response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "s",
                    "output_model_name": "yolox-s-bolt",
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["dataset_export_id"] == dataset_export.dataset_export_id
        assert payload["dataset_export_manifest_key"] == dataset_export.manifest_object_key
        assert payload["queue_name"] == YOLOX_TRAINING_QUEUE_NAME

        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.task_kind == "yolox-training"
        assert task_detail.task.task_spec["dataset_export_id"] == dataset_export.dataset_export_id
        assert task_detail.task.task_spec["dataset_export_manifest_key"] == dataset_export.manifest_object_key
        assert task_detail.task.state == "queued"
        assert any(event.message == "yolox training queued" for event in task_detail.events)

        queue_task = queue_backend.get_task(
            queue_name=YOLOX_TRAINING_QUEUE_NAME,
            task_id=payload["queue_task_id"],
        )
        assert queue_task is not None
        assert queue_task.payload["task_id"] == payload["task_id"]
    finally:
        session_factory.engine.dispose()


def test_create_yolox_training_task_accepts_manifest_key(tmp_path: Path) -> None:
    """验证训练创建接口可以通过 manifest_object_key 反查 DatasetExport。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-2",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-2/manifest.json"
        ),
    )
    try:
        with client:
            response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "recipe_id": "yolox-default",
                    "model_scale": "m",
                    "output_model_name": "yolox-m-bolt",
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["dataset_export_id"] == dataset_export.dataset_export_id
        assert payload["dataset_export_manifest_key"] == dataset_export.manifest_object_key
        assert payload["dataset_version_id"] == dataset_export.dataset_version_id
    finally:
        session_factory.engine.dispose()


def test_create_yolox_training_task_rejects_mismatched_export_id_and_manifest_key(
    tmp_path: Path,
) -> None:
    """验证当 dataset_export_id 与 manifest_object_key 不属于同一资源时接口会拒绝。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export_a = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-a",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-a/manifest.json"
        ),
    )
    dataset_export_b = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-b",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-b/manifest.json"
        ),
    )
    try:
        with client:
            response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_a.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export_b.manifest_object_key,
                    "recipe_id": "yolox-default",
                    "model_scale": "s",
                    "output_model_name": "yolox-s-bolt",
                },
            )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "invalid_request"
        assert payload["error"]["message"] == "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport"
    finally:
        session_factory.engine.dispose()


def test_list_yolox_training_tasks_filters_by_dataset_export_id(tmp_path: Path) -> None:
    """验证训练任务列表接口可以按 DatasetExport 边界筛选。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export_a = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-list-a",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-list-a/manifest.json"
        ),
    )
    dataset_export_b = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-list-b",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-list-b/manifest.json"
        ),
    )
    try:
        with client:
            create_a = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_a.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "s",
                    "output_model_name": "yolox-s-a",
                },
            )
            create_b = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_b.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "m",
                    "output_model_name": "yolox-m-b",
                },
            )
            response = client.get(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                params={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_a.dataset_export_id,
                },
            )

        assert create_a.status_code == 202
        assert create_b.status_code == 202
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["dataset_export_id"] == dataset_export_a.dataset_export_id
        assert payload[0]["recipe_id"] == "yolox-default"
        assert payload[0]["model_scale"] == "s"
        assert payload[0]["state"] == "queued"
    finally:
        session_factory.engine.dispose()


def test_get_yolox_training_task_detail_returns_completed_result(tmp_path: Path) -> None:
    """验证训练任务详情接口会返回完成态结果和事件流。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-detail-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-detail-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "s",
                    "output_model_name": "yolox-s-detail",
                },
            )

        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]
        assert _run_yolox_training_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        with client:
            detail_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}",
                headers=_build_training_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["task_id"] == task_id
        assert payload["state"] == "succeeded"
        assert payload["dataset_export_id"] == dataset_export.dataset_export_id
        assert payload["checkpoint_object_key"].endswith("/best_ckpt.pth")
        assert payload["summary_object_key"].endswith("/training-summary.json")
        assert payload["training_summary"]["implementation_mode"] == "placeholder"
        assert "reference_code_root" not in payload["metadata"]
        assert "reference_code_root" not in payload["training_summary"]
        assert "reference_code_root" not in payload["result"].get("summary", {})
        assert any(event["message"] == "yolox training started" for event in payload["events"])
        assert any(event["message"] == "yolox training completed" for event in payload["events"])
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的训练 API 测试客户端。"""

    database_path = tmp_path / "amvision-training-api.db"
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


def _seed_completed_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
    manifest_object_key: str,
) -> DatasetExport:
    """写入一个已完成的 DatasetExport 资源和最小 manifest 文件。"""

    export_path = manifest_object_key.rsplit("/manifest.json", 1)[0]
    dataset_export = DatasetExport(
        dataset_export_id=dataset_export_id,
        dataset_id="dataset-1",
        project_id="project-1",
        dataset_version_id=f"dataset-version-{dataset_export_id}",
        format_id=COCO_DETECTION_DATASET_FORMAT,
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
        task_id=f"task-{dataset_export_id}",
        export_path=export_path,
        manifest_object_key=manifest_object_key,
        split_names=("train",),
        sample_count=1,
        category_names=("bolt",),
    )

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    dataset_storage.write_json(
        manifest_object_key,
        {
            "format_id": COCO_DETECTION_DATASET_FORMAT,
            "dataset_version_id": dataset_export.dataset_version_id,
            "category_names": ["bolt"],
            "splits": [
                {
                    "name": "train",
                    "image_root": f"{export_path}/images/train",
                    "annotation_file": f"{export_path}/annotations/instances_train.json",
                    "sample_count": 1,
                }
            ],
            "metadata": {"source_dataset_id": "dataset-1"},
        },
    )
    dataset_storage.write_json(
        f"{export_path}/annotations/instances_train.json",
        {"images": [], "annotations": [], "categories": []},
    )
    dataset_storage.write_bytes(f"{export_path}/images/train/train-1.jpg", b"fake-image")
    return dataset_export


def _build_training_headers() -> dict[str, str]:
    """构建具备训练创建所需 scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "datasets:read,tasks:read,tasks:write",
    }


def _run_yolox_training_worker_once(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> bool:
    """执行一次 YOLOX 训练队列 worker。"""

    worker = YoloXTrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-training-worker",
    )
    return worker.run_once()