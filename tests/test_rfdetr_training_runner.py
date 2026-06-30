"""RF-DETR 训练 runner 回归测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.service.application.backends import TrainingBackendRunRequest
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
from backend.workers.training.rfdetr_trainer_runner import SqlAlchemyRfdetrTrainerRunner


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
