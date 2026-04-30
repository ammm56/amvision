"""YOLOX 训练 worker 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import cv2
import numpy as np

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.models.yolox_detection_training import (
    YoloXDetectionTrainingExecutionResult,
    YoloXTrainingEpochProgress,
)
import backend.service.application.models.yolox_training_service as yolox_training_service_module
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXPretrainedRegistrationRequest,
)
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
                model_scale="nano",
                output_model_name="yolox-s-bolt",
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                input_size=(64, 64),
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
        assert completed_task.task.result["latest_checkpoint_object_key"].endswith("/latest_ckpt.pth")
        assert completed_task.task.result["validation_metrics_object_key"].endswith("/validation-metrics.json")
        assert completed_task.task.result["summary_object_key"].endswith("/training-summary.json")
        assert completed_task.task.result["summary"]["implementation_mode"] == "yolox-detection-minimal"
        assert completed_task.task.result["summary"]["precision"] == "fp32"
        assert completed_task.task.result["summary"]["evaluation_interval"] == 5
        assert completed_task.task.result["summary"]["validation"]["enabled"] is True
        assert completed_task.task.result["summary"]["validation"]["evaluation_interval"] == 5
        assert "map50" in completed_task.task.result["summary"]["validation"]["final_metrics"]
        assert "map50_95" in completed_task.task.result["summary"]["validation"]["final_metrics"]
        assert completed_task.task.result["summary"]["warm_start"]["enabled"] is False
        assert completed_task.task.result["summary"]["model_version_id"]
        assert any(event.message == "yolox training started" for event in completed_task.events)
        assert any(event.message == "yolox training completed" for event in completed_task.events)
        assert any(event.event_type == "progress" for event in completed_task.events)

        progress_event = next(event for event in completed_task.events if event.event_type == "progress")
        assert progress_event.payload["progress"]["validation_ran"] is True
        assert progress_event.payload["progress"]["evaluation_interval"] == 5
        assert progress_event.payload["progress"]["evaluated_epochs"] == [1]
        assert "map50" in progress_event.payload["progress"]["validation_metrics"]
        assert "map50_95" in progress_event.payload["progress"]["validation_metrics"]

        assert dataset_storage.resolve(completed_task.task.result["checkpoint_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["latest_checkpoint_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["metrics_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["validation_metrics_object_key"]).is_file()
        assert dataset_storage.resolve(completed_task.task.result["summary_object_key"]).is_file()

        validation_metrics_payload = dataset_storage.read_json(
            completed_task.task.result["validation_metrics_object_key"]
        )
        assert validation_metrics_payload["evaluation_interval"] == 5
        assert "map50" in validation_metrics_payload["final_metrics"]
        assert "map50_95" in validation_metrics_payload["final_metrics"]

        model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
        model_version = model_service.get_model_version(
            completed_task.task.result["summary"]["model_version_id"]
        )
        assert model_version is not None
        assert model_version.training_task_id == submission.task_id
        assert model_version.metadata["dataset_export_id"] == "dataset-export-worker-1"
        assert (
            model_version.metadata["manifest_object_key"]
            == "projects/project-1/datasets/dataset-1/exports/dataset-export-worker-1/manifest.json"
        )

        assert worker.run_once() is False
    finally:
        session_factory.engine.dispose()


def test_yolox_training_worker_can_warm_start_from_existing_model_version(tmp_path: Path) -> None:
    """验证训练 worker 可以使用平台级预训练 ModelVersion 做 warm start。"""

    session_factory, dataset_storage, queue_backend = _create_worker_runtime(tmp_path)
    _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-worker-warm-start-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-worker-warm-start-1/manifest.json"
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
        first_submission = service.submit_training_task(
            YoloXTrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-worker-warm-start-1",
                recipe_id="yolox-default",
                model_scale="nano",
                output_model_name="yolox-s-bolt-base",
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                input_size=(64, 64),
            ),
            created_by="user-1",
        )
        assert worker.run_once() is True
        first_completed_task = SqlAlchemyTaskService(session_factory).get_task(
            first_submission.task_id,
            include_events=True,
        )
        model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
        warm_start_model_version_id = model_service.register_pretrained(
            YoloXPretrainedRegistrationRequest(
                model_name="yolox",
                storage_uri=first_completed_task.task.result["checkpoint_object_key"],
                model_scale="nano",
                model_version_id="model-version-platform-pretrained-nano",
                checkpoint_file_id="model-file-platform-pretrained-nano-checkpoint",
                metadata={"catalog_name": "generated-from-training"},
            )
        )

        second_submission = service.submit_training_task(
            YoloXTrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-worker-warm-start-1",
                recipe_id="yolox-default",
                model_scale="nano",
                output_model_name="yolox-s-bolt-finetuned",
                warm_start_model_version_id=warm_start_model_version_id,
                max_epochs=1,
                batch_size=1,
                precision="fp32",
                input_size=(64, 64),
            ),
            created_by="user-1",
        )

        assert worker.run_once() is True

        second_completed_task = SqlAlchemyTaskService(session_factory).get_task(
            second_submission.task_id,
            include_events=True,
        )
        warm_start_summary = second_completed_task.task.result["summary"]["warm_start"]
        assert warm_start_summary["enabled"] is True
        assert warm_start_summary["source_model_version_id"] == warm_start_model_version_id
        assert warm_start_summary["source_kind"] == "pretrained-reference"
        assert warm_start_summary["loaded_parameter_count"] > 0

        second_model_version_id = second_completed_task.task.result["summary"]["model_version_id"]
        second_model_version = model_service.get_model_version(second_model_version_id)
        assert second_model_version is not None
        assert second_model_version.parent_version_id == warm_start_model_version_id
    finally:
        session_factory.engine.dispose()


def test_training_service_writes_intermediate_validation_snapshot_on_evaluation_epoch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证评估轮完成后会立即把 validation snapshot 增量写入磁盘。"""

    session_factory, dataset_storage, queue_backend = _create_worker_runtime(tmp_path)
    _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-worker-incremental-validation-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-worker-incremental-validation-1/manifest.json"
        ),
    )
    service = SqlAlchemyYoloXTrainingTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_training_task(
        YoloXTrainingTaskRequest(
            project_id="project-1",
            dataset_export_id="dataset-export-worker-incremental-validation-1",
            recipe_id="yolox-default",
            model_scale="nano",
            output_model_name="yolox-s-incremental-validation",
            max_epochs=6,
            batch_size=1,
            precision="fp32",
            input_size=(64, 64),
        ),
        created_by="user-1",
    )
    expected_validation_metrics_object_key = (
        f"task-runs/training/{submission.task_id}/artifacts/reports/validation-metrics.json"
    )

    def fake_run_training(request):
        validation_snapshot = {
            "enabled": True,
            "split_name": "val",
            "sample_count": 1,
            "evaluation_interval": 5,
            "confidence_threshold": 0.01,
            "nms_threshold": 0.65,
            "best_metric_name": "map50_95",
            "best_metric_value": 0.41,
            "final_metrics": {
                "epoch": 5,
                "total_loss": 1.2,
                "map50": 0.62,
                "map50_95": 0.41,
            },
            "evaluated_epochs": [5],
            "epoch_history": [
                {
                    "epoch": 5,
                    "total_loss": 1.2,
                    "map50": 0.62,
                    "map50_95": 0.41,
                }
            ],
        }
        if request.epoch_callback is not None:
            request.epoch_callback(
                YoloXTrainingEpochProgress(
                    epoch=5,
                    max_epochs=6,
                    evaluation_interval=5,
                    validation_ran=True,
                    evaluated_epochs=(5,),
                    train_metrics={"total_loss": 0.8, "lr": 0.001},
                    validation_metrics={
                        "total_loss": 1.2,
                        "map50": 0.62,
                        "map50_95": 0.41,
                    },
                    validation_snapshot=validation_snapshot,
                    current_metric_name="val_map50_95",
                    current_metric_value=0.41,
                    best_metric_name="val_map50_95",
                    best_metric_value=0.41,
                )
            )
            snapshot_path = request.dataset_storage.resolve(expected_validation_metrics_object_key)
            assert snapshot_path.is_file() is True
            snapshot_payload = request.dataset_storage.read_json(expected_validation_metrics_object_key)
            assert snapshot_payload["evaluated_epochs"] == [5]
            assert snapshot_payload["final_metrics"]["map50"] == 0.62
            assert snapshot_payload["final_metrics"]["map50_95"] == 0.41

        return YoloXDetectionTrainingExecutionResult(
            checkpoint_bytes=b"best-checkpoint",
            latest_checkpoint_bytes=b"latest-checkpoint",
            metrics_payload={
                "implementation_mode": "fake-yolox-detection-minimal",
                "device": "cpu",
                "gpu_count": 0,
                "device_ids": [],
                "distributed_mode": "single-device",
                "precision": "fp32",
                "batch_size": 1,
                "max_epochs": 6,
                "evaluation_interval": 5,
                "input_size": [64, 64],
                "train_split_name": "train",
                "validation_split_name": "val",
                "sample_count": 2,
                "train_sample_count": 1,
                "validation_sample_count": 1,
                "category_names": ["bolt", "nut"],
                "best_metric_name": "val_map50_95",
                "best_metric_value": 0.41,
                "final_metrics": {"epoch": 6, "train_total_loss": 0.7},
                "epoch_history": [],
                "parameter_count": 1,
                "warm_start": {"enabled": False},
            },
            validation_metrics_payload=validation_snapshot,
            warm_start_summary={"enabled": False},
            implementation_mode="fake-yolox-detection-minimal",
            best_metric_name="val_map50_95",
            best_metric_value=0.41,
            evaluation_interval=5,
            category_names=("bolt", "nut"),
            split_names=("train", "val"),
            sample_count=2,
            train_sample_count=1,
            input_size=(64, 64),
            batch_size=1,
            max_epochs=6,
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
            precision="fp32",
            validation_split_name="val",
            validation_sample_count=1,
            parameter_count=1,
        )

    monkeypatch.setattr(
        yolox_training_service_module,
        "run_yolox_detection_training",
        fake_run_training,
    )

    try:
        result = service.process_training_task(submission.task_id)
        assert result.validation_metrics_object_key == expected_validation_metrics_object_key
        validation_metrics_payload = dataset_storage.read_json(expected_validation_metrics_object_key)
        assert validation_metrics_payload["evaluated_epochs"] == [5]
        assert validation_metrics_payload["final_metrics"]["map50"] == 0.62
        assert validation_metrics_payload["final_metrics"]["map50_95"] == 0.41
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
                    "sample_count": 1,
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
    dataset_storage.write_json(
        f"{export_path}/annotations/instances_train.json",
        {
            "images": [
                {
                    "id": 1,
                    "file_name": "train-1.jpg",
                    "width": 64,
                    "height": 64,
                }
            ],
            "annotations": [
                {
                    "id": 1,
                    "image_id": 1,
                    "category_id": 0,
                    "bbox": [8, 8, 24, 24],
                    "area": 576,
                    "iscrowd": 0,
                }
            ],
            "categories": [
                {"id": 0, "name": "bolt"},
                {"id": 1, "name": "nut"},
            ],
        },
    )
    dataset_storage.write_json(
        f"{export_path}/annotations/instances_val.json",
        {
            "images": [
                {
                    "id": 2,
                    "file_name": "val-1.jpg",
                    "width": 64,
                    "height": 64,
                }
            ],
            "annotations": [
                {
                    "id": 2,
                    "image_id": 2,
                    "category_id": 1,
                    "bbox": [10, 10, 16, 16],
                    "area": 256,
                    "iscrowd": 0,
                }
            ],
            "categories": [
                {"id": 0, "name": "bolt"},
                {"id": 1, "name": "nut"},
            ],
        },
    )
    dataset_storage.write_bytes(
        f"{export_path}/images/train/train-1.jpg",
        _build_test_jpeg_bytes(),
    )
    dataset_storage.write_bytes(
        f"{export_path}/images/val/val-1.jpg",
        _build_test_jpeg_bytes(),
    )
    return dataset_export


def _build_test_jpeg_bytes() -> bytes:
    """构建一个可被 cv2 正常读取的最小 JPEG 图片。"""

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return encoded.tobytes()