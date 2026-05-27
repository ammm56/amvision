"""YOLOv8 detection 适配器最小行为测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.contracts.datasets.exports.dataset_formats import YOLO_DETECTION_DATASET_FORMAT
from backend.queue.local_file_queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8BuildRegistration,
    YoloV8TrainingOutputRegistration,
)
from backend.service.application.models.yolov8_training_service import (
    SqlAlchemyYoloV8TrainingTaskService,
    YoloV8TrainingTaskRequest,
)
from backend.service.application.runtime.yolov8_runtime_target import (
    RuntimeTargetResolveRequest,
    SqlAlchemyYoloV8RuntimeTargetResolver,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.files.detection_model_file_types import YOLOV8_DETECTION_FILE_TYPES
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.training.yolov8_training_queue_worker import YoloV8TrainingQueueWorker


def test_yolov8_model_service_registers_yolov8_specific_file_types() -> None:
    """验证 YOLOv8 detection 模型登记会落到自身文件类型集合。"""

    service = _create_model_service()
    model_version_id = service.register_training_output(
        YoloV8TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-1",
            model_name="yolov8",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-1",
            checkpoint_file_uri="memory://runs/yolov8/best.pt",
            labels_file_id="labels-file-1",
            labels_file_uri="memory://runs/yolov8/labels.txt",
            metrics_file_id="metrics-file-1",
            metrics_file_uri="memory://runs/yolov8/metrics.json",
        )
    )
    model_build_id = service.register_build(
        YoloV8BuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id="build-file-1",
            build_file_uri="memory://runs/yolov8/model.onnx",
        )
    )

    model_version = service.get_model_version(model_version_id)
    model = service.get_model(model_version.model_id if model_version is not None else "")
    version_files = service.list_model_files(model_version_id=model_version_id)
    build_files = service.list_model_files(model_build_id=model_build_id)

    assert model_version is not None
    assert model is not None
    assert model.model_type == "yolov8"
    assert {item.file_type for item in version_files} == {
        YOLOV8_DETECTION_FILE_TYPES.checkpoint_file_type,
        YOLOV8_DETECTION_FILE_TYPES.label_map_file_type,
        YOLOV8_DETECTION_FILE_TYPES.training_metrics_file_type,
    }
    assert {item.file_type for item in build_files} == {
        YOLOV8_DETECTION_FILE_TYPES.onnx_file_type,
    }


def test_yolov8_conversion_planner_uses_yolov8_file_types() -> None:
    """验证 YOLOv8 detection 转换规划会生成自身文件类型。"""

    planner = DefaultYoloV8ConversionPlanner()

    plan = planner.build_plan(
        YoloV8ConversionPlanningRequest(
            project_id="project-1",
            source_model_version_id="model-version-1",
            target_formats=("onnx", "openvino-ir", "tensorrt-engine"),
        )
    )

    assert plan.steps[0].required_file_type == YOLOV8_DETECTION_FILE_TYPES.checkpoint_file_type
    assert tuple(step.produced_file_type for step in plan.steps if step.produced_file_type is not None) == (
        YOLOV8_DETECTION_FILE_TYPES.onnx_file_type,
        YOLOV8_DETECTION_FILE_TYPES.onnx_optimized_file_type,
        YOLOV8_DETECTION_FILE_TYPES.openvino_ir_file_type,
        YOLOV8_DETECTION_FILE_TYPES.tensorrt_engine_file_type,
    )


def test_yolov8_runtime_target_resolver_returns_yolov8_snapshot(tmp_path: Path) -> None:
    """验证 YOLOv8 detection 运行时解析会返回带模型分类的快照。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    checkpoint_object_key = "models/yolov8/best.pt"
    labels_object_key = "models/yolov8/labels.txt"
    build_object_key = "models/yolov8/model.onnx"
    dataset_storage.write_bytes(checkpoint_object_key, b"fake-checkpoint")
    dataset_storage.write_text(labels_object_key, "part\n")
    dataset_storage.write_bytes(build_object_key, b"fake-onnx")

    model_version_id = model_service.register_training_output(
        YoloV8TrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-1",
            model_name="yolov8",
            model_scale="s",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-1",
            checkpoint_file_uri=checkpoint_object_key,
            labels_file_id="labels-file-1",
            labels_file_uri=labels_object_key,
            metadata={"category_names": ["part"], "input_size": [640, 640]},
        )
    )
    model_build_id = model_service.register_build(
        YoloV8BuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="onnx",
            build_file_id="build-file-1",
            build_file_uri=build_object_key,
        )
    )

    resolver = SqlAlchemyYoloV8RuntimeTargetResolver(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    snapshot = resolver.resolve_target(
        RuntimeTargetResolveRequest(
            project_id="project-1",
            model_build_id=model_build_id,
        )
    )

    assert snapshot.model_type == "yolov8"
    assert snapshot.runtime_backend == "onnxruntime"
    assert snapshot.runtime_artifact_file_type == YOLOV8_DETECTION_FILE_TYPES.onnx_file_type
    assert snapshot.runtime_artifact_path == dataset_storage.resolve(build_object_key)
    assert snapshot.checkpoint_path == dataset_storage.resolve(checkpoint_object_key)
    assert snapshot.labels == ("part",)


def test_yolov8_training_task_service_submits_task_and_worker_completes_training(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 detection 训练入口和 worker 已接通。"""

    session_factory = _create_session_factory()
    dataset_storage = _create_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    _save_completed_dataset_export(session_factory)
    _write_completed_dataset_export_files(dataset_storage)
    service = SqlAlchemyYoloV8TrainingTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    worker = YoloV8TrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolov8-training-worker",
    )

    submission = service.submit_training_task(
        YoloV8TrainingTaskRequest(
            project_id="project-1",
            dataset_export_id="dataset-export-1",
            recipe_id="recipe-1",
            model_scale="s",
            output_model_name="yolov8-s-workpiece",
            input_size=(64, 64),
            max_epochs=1,
            batch_size=1,
            precision="fp32",
        )
    )

    assert submission.status == "queued"
    assert queue_backend.get_task(
        queue_name=submission.queue_name,
        task_id=submission.queue_task_id,
    ) is not None

    assert worker.run_once() is True

    task_detail = SqlAlchemyTaskService(session_factory).get_task(
        submission.task_id,
        include_events=True,
    )

    assert task_detail.task.state == "succeeded"
    assert task_detail.task.metadata["model_type"] == "yolov8"
    assert task_detail.task.task_spec["task_type"] == "detection"
    assert task_detail.task.error_message is None
    assert task_detail.task.result["checkpoint_object_key"].endswith("/best.pt")
    assert task_detail.task.result["latest_checkpoint_object_key"].endswith("/latest.pt")
    assert task_detail.task.result["summary"]["implementation_mode"] == "yolov8-detection"
    assert task_detail.task.result["summary"]["dataset_export_id"] == "dataset-export-1"
    assert task_detail.task.result["summary"]["dataset_version_id"] == "dataset-version-1"
    assert task_detail.task.result["summary"]["training_config"]["recipe_id"] == "recipe-1"
    assert task_detail.task.result["summary"]["output_files"]["checkpoint_object_key"].endswith(
        "/best.pt"
    )
    assert task_detail.task.result["summary"]["model_version_id"]
    assert any(
        event.message == "yolov8 training completed"
        for event in task_detail.events
    )
    assert any(event.event_type == "progress" for event in task_detail.events)
    assert dataset_storage.resolve(task_detail.task.result["checkpoint_object_key"]).is_file()
    assert dataset_storage.resolve(task_detail.task.result["metrics_object_key"]).is_file()

    model_service = SqlAlchemyYoloV8ModelService(session_factory=session_factory)
    model_version = model_service.get_model_version(task_detail.task.result["model_version_id"])
    assert model_version is not None
    assert model_version.training_task_id == submission.task_id


def test_yolov8_training_task_service_rejects_unsupported_model_scale(tmp_path: Path) -> None:
    """验证 YOLOv8 detection 训练入口会拒绝不支持的模型 scale。"""

    service = SqlAlchemyYoloV8TrainingTaskService(
        session_factory=_create_session_factory(),
        queue_backend=LocalFileQueueBackend(
            LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
        ),
    )

    with pytest.raises(InvalidRequestError, match="model_scale"):
        service.submit_training_task(
            YoloV8TrainingTaskRequest(
                project_id="project-1",
                dataset_export_id="dataset-export-1",
                recipe_id="recipe-1",
                model_scale="tiny",
                output_model_name="invalid-yolov8",
            )
        )


def _create_session_factory() -> SessionFactory:
    """创建绑定内存数据库的 SessionFactory。"""

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    return session_factory


def _create_model_service() -> SqlAlchemyYoloV8ModelService:
    """创建测试使用的 YOLOv8 detection 模型服务。"""

    return SqlAlchemyYoloV8ModelService(session_factory=_create_session_factory())


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建测试使用的本地数据文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage")))


def _save_completed_dataset_export(session_factory: SessionFactory) -> None:
    """写入一条已完成的 detection DatasetExport 供训练入口复用。"""

    dataset_export = DatasetExport(
        dataset_export_id="dataset-export-1",
        dataset_id="dataset-1",
        project_id="project-1",
        dataset_version_id="dataset-version-1",
        format_id=YOLO_DETECTION_DATASET_FORMAT,
        task_type="detection",
        status="completed",
        created_at="2026-05-26T00:00:00+00:00",
        export_path="exports/dataset-export-1",
        manifest_object_key="exports/dataset-export-1/manifest.json",
        split_names=("train", "val"),
        sample_count=8,
        category_names=("part",),
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(dataset_export)
        unit_of_work.commit()
    finally:
        unit_of_work.close()


def _write_completed_dataset_export_files(dataset_storage: LocalDatasetStorage) -> None:
    """写入一套最小 YOLO detection 导出目录。"""

    export_root = "exports/dataset-export-1"
    train_image_key = f"{export_root}/images/train/sample-train.jpg"
    val_image_key = f"{export_root}/images/val/sample-val.jpg"
    train_annotation_key = f"{export_root}/annotations/instances_train.json"
    val_annotation_key = f"{export_root}/annotations/instances_val.json"
    manifest_key = f"{export_root}/manifest.json"

    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[12:36, 18:40] = (255, 255, 255)
    for image_key in (train_image_key, val_image_key):
        target_path = dataset_storage.resolve(image_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(target_path), image)

    train_annotation = {
        "images": [{"id": 1, "file_name": "sample-train.jpg", "width": 64, "height": 64}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 0, "bbox": [18, 12, 22, 24]}],
        "categories": [{"id": 0, "name": "part"}],
    }
    val_annotation = {
        "images": [{"id": 2, "file_name": "sample-val.jpg", "width": 64, "height": 64}],
        "annotations": [{"id": 2, "image_id": 2, "category_id": 0, "bbox": [16, 10, 20, 22]}],
        "categories": [{"id": 0, "name": "part"}],
    }
    dataset_storage.write_json(train_annotation_key, train_annotation)
    dataset_storage.write_json(val_annotation_key, val_annotation)
    dataset_storage.write_json(
        manifest_key,
        {
            "format_id": YOLO_DETECTION_DATASET_FORMAT,
            "splits": [
                {
                    "name": "train",
                    "image_root": f"{export_root}/images/train",
                    "annotation_file": train_annotation_key,
                },
                {
                    "name": "val",
                    "image_root": f"{export_root}/images/val",
                    "annotation_file": val_annotation_key,
                },
            ],
        },
    )
