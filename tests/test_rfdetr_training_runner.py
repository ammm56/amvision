"""RF-DETR 训练 runner 回归测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings, QueueMessage
from backend.service.application.backends import TrainingBackendRunRequest
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training import segmentation_training_service
from backend.service.application.models.training.rfdetr_segmentation import (
    RfdetrSegmentationTrainingExecutionResult,
)
from backend.service.application.models.training.segmentation_training_service import (
    SegmentationTrainingRequest,
    SqlAlchemySegmentationTrainingService,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.service.application.models.training import rfdetr_detection_task_service
from backend.workers.training.rfdetr_training_queue_worker import RfdetrTrainingQueueWorker
from backend.workers.training.rfdetr_trainer_runner import SqlAlchemyRfdetrTrainerRunner


def test_rfdetr_training_queue_worker_reads_explicit_task_type() -> None:
    """验证 RF-DETR 队列 worker 使用负载中的显式 task_type。"""

    worker = RfdetrTrainingQueueWorker.__new__(RfdetrTrainingQueueWorker)
    queue_task = QueueMessage(
        queue_name="rfdetr-trainings",
        task_id="queue-task-1",
        payload={"task_id": "task-1", "task_type": "segmentation"},
    )

    assert worker._read_task_type(queue_task) == "segmentation"


def test_rfdetr_training_queue_worker_rejects_missing_task_type() -> None:
    """验证 RF-DETR 队列 worker 拒绝缺少 task_type 的负载。"""

    worker = RfdetrTrainingQueueWorker.__new__(RfdetrTrainingQueueWorker)
    queue_task = QueueMessage(
        queue_name="rfdetr-trainings",
        task_id="queue-task-1",
        payload={"task_id": "task-1"},
    )

    with pytest.raises(InvalidRequestError):
        worker._read_task_type(queue_task)


def test_rfdetr_trainer_runner_reads_task_spec_without_queue_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 RF-DETR runner 不依赖旧 metadata.queue_payload 字段。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'runner.db').as_posix()}")
    )
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    manifest_key = "exports/rfdetr-detection/manifest.json"
    dataset_storage.write_json(
        manifest_key,
        {
            "format_id": "coco-detection-v1",
            "classes": [{"id": 1, "name": "part"}],
        },
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(
            DatasetExport(
                dataset_export_id="dataset-export-1",
                dataset_id="dataset-1",
                project_id="project-1",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
                task_type="detection",
                status="completed",
                created_at="2026-06-23T00:00:00+00:00",
                manifest_object_key=manifest_key,
                split_names=("train",),
                sample_count=1,
                category_names=("part",),
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()
    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    task_record = task_service.create_task(
        CreateTaskRequest(
            project_id="project-1",
            task_kind="rfdetr-training",
            display_name="rfdetr runner payload smoke",
            task_spec={
                "project_id": "project-1",
                "recipe_id": "default",
                "model_type": "rfdetr",
                "task_type": "detection",
                "model_scale": "nano",
                "output_model_name": "rfdetr-nano-smoke",
                "dataset_export_id": "dataset-export-1",
                "dataset_export_manifest_key": manifest_key,
                "dataset_version_id": "dataset-version-1",
                "format_id": "coco-detection-v1",
                "batch_size": 1,
                "max_epochs": 1,
                "precision": "fp32",
                "input_size": [384, 384],
                "extra_options": {"smoke_validation": True},
            },
            metadata={
                "model_type": "rfdetr",
                "task_type": "detection",
            },
        )
    )
    captured_requests = []

    def _fake_run_rfdetr_training(request):
        captured_requests.append(request)
        return SimpleNamespace(
            best_metric_value=0.75,
            best_metric_name="map50",
                latest_checkpoint_bytes=b"fake-rfdetr-checkpoint",
                metrics_payload={"train_loss": 1.0},
                validation_metrics_payload={"map50": 0.75},
                warm_start_summary={"enabled": False},
                labels=("part",),
                aligned_input_size=(384, 384),
            )

    monkeypatch.setattr(
        rfdetr_detection_task_service,
        "run_rfdetr_training",
        _fake_run_rfdetr_training,
    )

    try:
        result = SqlAlchemyRfdetrTrainerRunner(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ).run_training(
            TrainingBackendRunRequest(
                training_task_id=task_record.task_id,
                model_type="rfdetr",
                task_type="detection",
            )
        )
    finally:
        session_factory.engine.dispose()

    assert captured_requests
    assert captured_requests[0].manifest_payload["format_id"] == "coco-detection-v1"
    assert captured_requests[0].batch_size == 1
    assert captured_requests[0].input_size == (384, 384)
    assert result.dataset_export_id == "dataset-export-1"
    assert result.format_id == "coco-detection-v1"
    assert result.best_metric_value == 0.75
    updated_task = SqlAlchemyTaskService(session_factory=session_factory).get_task(
        task_record.task_id
    ).task
    assert updated_task.state == "succeeded"
    assert updated_task.result["model_version_id"]
    assert dataset_storage.resolve(result.checkpoint_object_key).is_file()
    assert dataset_storage.resolve(result.metrics_object_key).is_file()


def test_rfdetr_trainer_runner_routes_segmentation_task_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 RF-DETR runner 按 task_type 执行 segmentation full-core 服务。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'runner-seg.db').as_posix()}")
    )
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files-seg"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-seg"))
    )
    manifest_key = "exports/rfdetr-segmentation/manifest.json"
    dataset_storage.write_json(
        manifest_key,
        {
            "format_id": "coco-instance-seg-v1",
            "classes": [{"id": 1, "name": "part"}],
        },
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(
            DatasetExport(
                dataset_export_id="dataset-export-seg-1",
                dataset_id="dataset-1",
                project_id="project-1",
                dataset_version_id="dataset-version-seg-1",
                format_id="coco-instance-seg-v1",
                task_type="segmentation",
                status="completed",
                created_at="2026-06-23T00:00:00+00:00",
                manifest_object_key=manifest_key,
                split_names=("train",),
                sample_count=1,
                category_names=("part",),
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    training_service = SqlAlchemySegmentationTrainingService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = training_service.submit_training_task(
        SegmentationTrainingRequest(
            project_id="project-1",
            recipe_id="rfdetr-seg-runner",
            model_type="rfdetr",
            model_scale="nano",
            output_model_name="rfdetr-seg-runner",
            dataset_export_id="dataset-export-seg-1",
            max_epochs=1,
            batch_size=1,
            input_size=(64, 64),
            precision="fp32",
            extra_options={"device": "cpu"},
        )
    )
    captured_requests = []

    def _fake_run_rfdetr_segmentation_training(request):
        captured_requests.append(request)
        return RfdetrSegmentationTrainingExecutionResult(
            best_metric_value=0.66,
            best_metric_name="mask_map50",
            latest_checkpoint_bytes=b"fake-rfdetr-seg-checkpoint",
            metrics_payload={"train_loss": 1.0},
            validation_metrics_payload={"mask_map50": 0.66},
            labels=("part",),
            aligned_input_size=(64, 64),
            warm_start_summary={"enabled": False},
        )

    monkeypatch.setattr(
        segmentation_training_service,
        "run_rfdetr_segmentation_training",
        _fake_run_rfdetr_segmentation_training,
    )

    try:
        result = SqlAlchemyRfdetrTrainerRunner(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ).run_training(
            TrainingBackendRunRequest(
                training_task_id=str(submission["task_id"]),
                model_type="rfdetr",
                task_type="segmentation",
            )
        )
    finally:
        session_factory.engine.dispose()

    assert captured_requests
    assert captured_requests[0].manifest_payload["format_id"] == "coco-instance-seg-v1"
    assert captured_requests[0].model_scale == "nano"
    assert result.dataset_export_id == "dataset-export-seg-1"
    assert result.format_id == "coco-instance-seg-v1"
    assert result.best_metric_name == "mask_map50"
    assert result.best_metric_value == 0.66
    updated_task = SqlAlchemyTaskService(session_factory=session_factory).get_task(
        str(submission["task_id"])
    ).task
    assert updated_task.state == "succeeded"
    assert updated_task.result["summary"]["implementation_mode"] == (
        "rfdetr-full-core-segmentation"
    )
    assert dataset_storage.resolve(result.checkpoint_object_key).is_file()
    assert dataset_storage.resolve(result.metrics_object_key).is_file()
