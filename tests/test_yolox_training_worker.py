"""YOLOX 训练 worker 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.models.yolox_training_service import SqlAlchemyYoloXTrainingTaskService, YoloXTrainingTaskRequest
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.workers.training.yolox_training_queue_worker import YoloXTrainingQueueWorker


def test_yolox_training_worker_advances_task_from_queued_to_succeeded(tmp_path: Path) -> None:
    """验证 yolox-trainings worker 会把训练任务从 queued 推进到 succeeded。"""

    session_factory, dataset_storage, queue_backend = _create_worker_runtime(tmp_path)
    _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-worker-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-worker-1/manifest.json"
        ),
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )
    worker = YoloXTrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-training-worker",
    )
    try:
        submission = service.submit_training_task(
            YoloXTrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-worker-1",
                recipe_id="yolox-default",
                model_scale="s",
                output_model_name="yolox-s-bolt",
            ),
            created_by="user-1",
        )

        queued_task = SqlAlchemyTaskService(session_factory).get_task(
            submission.task_id,
            include_events=True,
        )
        assert queued_task.task.state == "queued"

        assert worker.run_once() is True

        completed_task = SqlAlchemyTaskService(session_factory).get_task(
            submission.task_id,
            include_events=True,
        )
        assert completed_task.task.state == "succeeded"
        assert completed_task.task.started_at is not None
        assert completed_task.task.finished_at is not None
        assert completed_task.task.result["dataset_export_id"] == "dataset-export-worker-1"
        assert completed_task.task.result["checkpoint_object_key"].endswith("/best_ckpt.pth")
        assert completed_task.task.result["summary_object_key"].endswith("/training-summary.json")
        assert completed_task.task.result["summary"]["implementation_mode"] == "placeholder"
        assert any(event.message == "yolox training started" for event in completed_task.events)
        assert any(event.message == "yolox training completed" for event in completed_task.events)

        assert dataset_storage.resolve(completed_task.task.result["checkpoint_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["metrics_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["summary_object_key"]).is_file()

        assert worker.run_once() is False
    finally:
        session_factory.engine.dispose()


def _create_worker_runtime(
    tmp_path: Path,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建测试 worker 运行所需的数据库、文件存储和队列。"""

    database_path = tmp_path / "amvision-yolox-training-worker.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    return session_factory, dataset_storage, queue_backend


def _seed_completed_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
    manifest_object_key: str,
) -> DatasetExport:
    """写入一个已完成的 DatasetExport 和最小 manifest 文件。"""

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
        split_names=("train", "val"),
        sample_count=3,
        category_names=("bolt", "nut"),
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
            "category_names": ["bolt", "nut"],
            "splits": [
                {
                    "name": "train",
                    "image_root": f"{export_path}/images/train",
                    "annotation_file": f"{export_path}/annotations/instances_train.json",
                    "sample_count": 2,
                },
                {
                    "name": "val",
                    "image_root": f"{export_path}/images/val",
                    "annotation_file": f"{export_path}/annotations/instances_val.json",
                    "sample_count": 1,
                },
            ],
            "metadata": {"source_dataset_id": "dataset-1"},
        },
    )
    return dataset_export