"""YOLOv8 detection 适配器最小行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.contracts.datasets.exports.dataset_formats import YOLO_DETECTION_DATASET_FORMAT
from backend.queue.local_file_queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
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
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.files.detection_model_file_types import YOLOV8_DETECTION_FILE_TYPES
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


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


def test_yolov8_training_task_service_submits_task_and_fails_with_clear_backend_message(
    tmp_path: Path,
) -> None:
    """验证 YOLOv8 detection 训练入口已接通，执行后端未实现时给出明确失败。"""

    session_factory = _create_session_factory()
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    _save_completed_dataset_export(session_factory)
    service = SqlAlchemyYoloV8TrainingTaskService(
        session_factory=session_factory,
        queue_backend=queue_backend,
    )

    submission = service.submit_training_task(
        YoloV8TrainingTaskRequest(
            project_id="project-1",
            dataset_export_id="dataset-export-1",
            recipe_id="recipe-1",
            model_scale="s",
            output_model_name="yolov8-s-workpiece",
            input_size=(640, 640),
        )
    )

    assert submission.status == "queued"
    assert queue_backend.get_task(
        queue_name=submission.queue_name,
        task_id=submission.queue_task_id,
    ) is not None

    with pytest.raises(ServiceConfigurationError, match="尚未接通"):
        service.process_training_task(submission.task_id)

    task_detail = service.task_service.get_task(submission.task_id, include_events=True)

    assert task_detail.task.state == "failed"
    assert task_detail.task.metadata["model_type"] == "yolov8"
    assert task_detail.task.task_spec["task_type"] == "detection"
    assert task_detail.task.error_message == "当前 YOLOv8 detection 训练执行后端尚未接通"
    assert any(
        event.message == "yolov8 detection training backend not implemented yet"
        for event in task_detail.events
    )


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
