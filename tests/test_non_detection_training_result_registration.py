"""非 detection 训练结果正式登记回主链的定向验证。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.datasets.exports.dataset_formats import (
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.models.training import (
    yolo11_classification_training_service as yolo11_classification_service_module,
)
from backend.service.application.models.training import (
    yolo_primary_pose_training_service as pose_service_module,
)
from backend.service.application.models.training import (
    yolo26_obb_training_service as yolo26_obb_service_module,
)
from backend.service.application.models.training import (
    yolo_primary_segmentation_training_service as segmentation_service_module,
)
from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
)
from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
)
from backend.service.application.models.training.yolo_primary_classification_training import (
    YoloPrimaryClassificationTrainingExecutionResult,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
    Yolo11ClassificationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_pose_training import (
    YoloPrimaryPoseTrainingExecutionResult,
)
from backend.service.application.models.training.yolo_primary_pose_training_service import (
    SqlAlchemyYoloPrimaryPoseTrainingTaskService,
    YoloPrimaryPoseTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_obb_training import (
    Yolo26ObbTrainingExecutionResult,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    SqlAlchemyYolo26ObbTrainingTaskService,
    Yolo26ObbTrainingTaskRequest,
)
from backend.service.application.models.training.yolo_primary_segmentation_training import (
    YoloPrimarySegmentationTrainingExecutionResult,
)
from backend.service.application.models.training.yolo_primary_segmentation_training_service import (
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
    YoloPrimarySegmentationTrainingTaskRequest,
)
from backend.service.application.runtime.runtime_target import (
    RuntimeTargetResolveRequest,
)
from backend.service.application.runtime.targets.yolo11 import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolo26 import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolov8 import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


def test_classification_training_registers_model_version_and_preserves_model_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 classification 训练结果会正式登记回模型主链。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    _seed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="classification-export-1",
        task_type="classification",
        format_id=IMAGENET_CLASSIFICATION_DATASET_FORMAT,
        manifest_object_key="exports/classification-export-1/manifest.json",
        category_names=("bolt", "nut"),
    )

    def _fake_run(request):
        assert request.model_type == "yolo11"
        return YoloPrimaryClassificationTrainingExecutionResult(
            best_metric_value=0.88,
            best_metric_name="val_top1_accuracy",
            latest_checkpoint_bytes=b"classification-checkpoint",
            metrics_payload={"final_metrics": {"loss": 0.12, "accuracy": 0.88}},
            validation_metrics_payload={"top1_accuracy": 0.88, "top5_accuracy": 1.0},
            labels=("bolt", "nut"),
        )

    monkeypatch.setattr(
        yolo11_classification_service_module,
        "run_yolo11_classification_service_training_execution",
        _fake_run,
    )

    service = SqlAlchemyYolo11ClassificationTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    submission = service.submit_training_task(
        Yolo11ClassificationTrainingTaskRequest(
            project_id="project-1",
            recipe_id="recipe-1",
            model_type="yolo11",
            model_scale="nano",
            output_model_name="yolo11-classifier",
            dataset_export_id="classification-export-1",
            max_epochs=2,
            batch_size=4,
            input_size=(64, 64),
            precision="fp32",
            extra_options={"device": "cpu"},
        )
    )
    queue_task = queue_backend.claim_next(
        queue_name=submission["queue_name"],
        worker_id="classification-worker",
    )
    assert queue_task is not None
    assert queue_task.payload["model_type"] == "yolo11"

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    task_record = task_service.get_task(submission["task_id"]).task
    result = service.process_training_task(
        task_record,
        model_type=str(queue_task.payload["model_type"]),
    )

    updated_task = task_service.get_task(submission["task_id"]).task
    assert updated_task.state == "succeeded"
    assert updated_task.result["model_version_id"] == result["model_version_id"]
    assert updated_task.result["labels_object_key"].endswith("/labels.txt")

    model_service = SqlAlchemyYolo11ModelService(session_factory=session_factory)
    model_files = model_service.list_model_files(
        model_version_id=result["model_version_id"]
    )
    file_types = {item.file_type for item in model_files}
    assert any(item.storage_uri.endswith("/best-checkpoint.pt") for item in model_files)
    assert any(item.storage_uri.endswith("/labels.txt") for item in model_files)
    assert any(item.storage_uri.endswith("/train-metrics.json") for item in model_files)
    assert "yolo11-label-map" in file_types
    assert "yolo11-training-metrics" in file_types

    runtime_target = SqlAlchemyYolo11RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=result["model_version_id"],
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )
    assert runtime_target.model_type == "yolo11"
    assert runtime_target.task_type == "classification"
    assert runtime_target.labels == ("bolt", "nut")


def test_segmentation_training_registers_model_version_and_preserves_model_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 segmentation 训练结果会正式登记回模型主链。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    _seed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="segmentation-export-1",
        task_type="segmentation",
        format_id=YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
        manifest_object_key="exports/segmentation-export-1/manifest.json",
        category_names=("part-a", "part-b", "part-c"),
    )

    def _fake_run(request):
        assert request.model_type == "yolo26"
        return YoloPrimarySegmentationTrainingExecutionResult(
            best_metric_value=0.51,
            best_metric_name="val_map50_95",
            latest_checkpoint_bytes=b"segmentation-checkpoint",
            metrics_payload={"final_metrics": {"loss": 0.45, "mask_loss": 0.22}},
            validation_metrics_payload={"map50": 0.63, "map50_95": 0.51},
            labels=("part-a", "part-b", "part-c"),
        )

    monkeypatch.setattr(
        segmentation_service_module,
        "run_yolo_primary_segmentation_training",
        _fake_run,
    )

    service = SqlAlchemyYoloPrimarySegmentationTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    submission = service.submit_training_task(
        YoloPrimarySegmentationTrainingTaskRequest(
            project_id="project-1",
            recipe_id="recipe-1",
            model_type="yolo26",
            model_scale="nano",
            output_model_name="yolo26-segmenter",
            dataset_export_id="segmentation-export-1",
            max_epochs=2,
            batch_size=2,
            input_size=(64, 64),
            precision="fp32",
            extra_options={"device": "cpu"},
        )
    )
    queue_task = queue_backend.claim_next(
        queue_name=submission["queue_name"],
        worker_id="segmentation-worker",
    )
    assert queue_task is not None
    assert queue_task.payload["model_type"] == "yolo26"

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    task_record = task_service.get_task(submission["task_id"]).task
    result = service.process_training_task(
        task_record,
        model_type=str(queue_task.payload["model_type"]),
    )

    updated_task = task_service.get_task(submission["task_id"]).task
    assert updated_task.state == "succeeded"
    assert updated_task.result["model_version_id"] == result["model_version_id"]
    assert updated_task.result["labels_object_key"].endswith("/labels.txt")

    model_service = SqlAlchemyYolo26ModelService(session_factory=session_factory)
    model_files = model_service.list_model_files(
        model_version_id=result["model_version_id"]
    )
    file_types = {item.file_type for item in model_files}
    assert any(item.storage_uri.endswith("/best-checkpoint.pt") for item in model_files)
    assert any(item.storage_uri.endswith("/labels.txt") for item in model_files)
    assert any(item.storage_uri.endswith("/train-metrics.json") for item in model_files)
    assert "yolo26-label-map" in file_types
    assert "yolo26-training-metrics" in file_types

    runtime_target = SqlAlchemyYolo26RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=result["model_version_id"],
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )
    assert runtime_target.model_type == "yolo26"
    assert runtime_target.task_type == "segmentation"
    assert runtime_target.labels == ("part-a", "part-b", "part-c")


def test_pose_training_registers_model_version_and_preserves_model_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 pose 训练结果会正式登记回模型主链。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    _seed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="pose-export-1",
        task_type="pose",
        format_id=YOLO_POSE_DATASET_FORMAT,
        manifest_object_key="exports/pose-export-1/manifest.json",
        category_names=("worker",),
    )

    def _fake_run(request):
        assert request.model_type == "yolov8"
        return YoloPrimaryPoseTrainingExecutionResult(
            best_metric_value=0.41,
            best_metric_name="val_map50_95",
            latest_checkpoint_bytes=b"pose-checkpoint",
            metrics_payload={"final_metrics": {"loss": 0.33, "kpt_loss": 0.09}},
            validation_metrics_payload={"map50": 0.52, "map50_95": 0.41},
            labels=("worker",),
        )

    monkeypatch.setattr(
        pose_service_module,
        "run_yolo_primary_pose_training",
        _fake_run,
    )

    service = SqlAlchemyYoloPrimaryPoseTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    submission = service.submit_training_task(
        YoloPrimaryPoseTrainingTaskRequest(
            project_id="project-1",
            recipe_id="recipe-1",
            model_type="yolov8",
            model_scale="nano",
            output_model_name="yolov8-pose",
            dataset_export_id="pose-export-1",
            max_epochs=2,
            batch_size=2,
            input_size=(64, 64),
            precision="fp32",
            extra_options={"device": "cpu"},
        )
    )
    queue_task = queue_backend.claim_next(
        queue_name=submission["queue_name"],
        worker_id="pose-worker",
    )
    assert queue_task is not None
    assert queue_task.payload["model_type"] == "yolov8"

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    task_record = task_service.get_task(submission["task_id"]).task
    result = service.process_training_task(
        task_record,
        model_type=str(queue_task.payload["model_type"]),
    )

    updated_task = task_service.get_task(submission["task_id"]).task
    assert updated_task.state == "succeeded"
    assert updated_task.result["model_version_id"] == result["model_version_id"]
    assert updated_task.result["labels_object_key"].endswith("/labels.txt")

    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    model_files = model_service.list_model_files(
        model_version_id=result["model_version_id"]
    )
    file_types = {item.file_type for item in model_files}
    assert any(item.storage_uri.endswith("/best-checkpoint.pt") for item in model_files)
    assert any(item.storage_uri.endswith("/labels.txt") for item in model_files)
    assert any(item.storage_uri.endswith("/train-metrics.json") for item in model_files)
    assert "yolov8-label-map" in file_types
    assert "yolov8-training-metrics" in file_types

    runtime_target = SqlAlchemyYoloV8RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=result["model_version_id"],
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )
    assert runtime_target.model_type == "yolov8"
    assert runtime_target.task_type == "pose"
    assert runtime_target.labels == ("worker",)


def test_obb_training_registers_model_version_and_preserves_model_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 obb 训练结果会正式登记回模型主链。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = _create_queue_backend(tmp_path)
    _seed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="obb-export-1",
        task_type="obb",
        format_id=DOTA_OBB_DATASET_FORMAT,
        manifest_object_key="exports/obb-export-1/manifest.json",
        category_names=("plate", "label"),
    )

    def _fake_run(request):
        assert request.model_type == "yolo26"
        return Yolo26ObbTrainingExecutionResult(
            best_metric_value=0.29,
            best_metric_name="val_loss",
            latest_checkpoint_bytes=b"obb-checkpoint",
            metrics_payload={"final_metrics": {"loss": 0.29, "angle_loss": 0.05}},
            validation_metrics_payload={"loss": 0.29},
            labels=("plate", "label"),
        )

    monkeypatch.setattr(
        yolo26_obb_service_module,
        "run_yolo26_obb_service_training_execution",
        _fake_run,
    )

    service = SqlAlchemyYolo26ObbTrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    submission = service.submit_training_task(
        Yolo26ObbTrainingTaskRequest(
            project_id="project-1",
            recipe_id="recipe-1",
            model_type="yolo26",
            model_scale="nano",
            output_model_name="yolo26-obb",
            dataset_export_id="obb-export-1",
            max_epochs=2,
            batch_size=2,
            input_size=(64, 64),
            precision="fp32",
            extra_options={"device": "cpu"},
        )
    )
    queue_task = queue_backend.claim_next(
        queue_name=submission["queue_name"],
        worker_id="obb-worker",
    )
    assert queue_task is not None
    assert queue_task.payload["model_type"] == "yolo26"

    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    task_record = task_service.get_task(submission["task_id"]).task
    result = service.process_training_task(
        task_record,
        model_type=str(queue_task.payload["model_type"]),
    )

    updated_task = task_service.get_task(submission["task_id"]).task
    assert updated_task.state == "succeeded"
    assert updated_task.result["model_version_id"] == result["model_version_id"]
    assert updated_task.result["labels_object_key"].endswith("/labels.txt")

    model_service = SqlAlchemyYolo26ModelService(session_factory=session_factory)
    model_files = model_service.list_model_files(
        model_version_id=result["model_version_id"]
    )
    file_types = {item.file_type for item in model_files}
    assert any(item.storage_uri.endswith("/best-checkpoint.pt") for item in model_files)
    assert any(item.storage_uri.endswith("/labels.txt") for item in model_files)
    assert any(item.storage_uri.endswith("/train-metrics.json") for item in model_files)
    assert "yolo26-label-map" in file_types
    assert "yolo26-training-metrics" in file_types

    runtime_target = SqlAlchemyYolo26RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    ).resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_version_id=result["model_version_id"],
            runtime_backend="pytorch",
            device_name="cpu",
        )
    )
    assert runtime_target.model_type == "yolo26"
    assert runtime_target.task_type == "obb"
    assert runtime_target.labels == ("plate", "label")


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(
        DatabaseSettings(url="sqlite+pysqlite:///:memory:")
    )
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
    )


def _create_queue_backend(tmp_path: Path) -> LocalFileQueueBackend:
    """创建测试使用的本地文件队列。"""

    return LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-storage"))
    )


def _seed_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
    task_type: str,
    format_id: str,
    manifest_object_key: str,
    category_names: tuple[str, ...],
) -> None:
    """写入一条最小已完成 DatasetExport。"""

    dataset_storage.write_json(
        manifest_object_key,
        {
            "category_names": list(category_names),
            "splits": [],
        },
    )
    dataset_export = DatasetExport(
        dataset_export_id=dataset_export_id,
        dataset_id=f"dataset-{dataset_export_id}",
        project_id="project-1",
        dataset_version_id=f"dataset-version-{dataset_export_id}",
        format_id=format_id,
        task_type=task_type,
        status="completed",
        created_at="2026-05-29T00:00:00+00:00",
        export_path=f"exports/{dataset_export_id}",
        manifest_object_key=manifest_object_key,
        split_names=("train", "val"),
        sample_count=8,
        category_names=category_names,
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()
