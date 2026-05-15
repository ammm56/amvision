"""数据集导出最小行为测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.contracts.datasets.exports.voc_detection_export import VOC_DETECTION_DATASET_FORMAT
from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_USERNAME
from backend.service.application.datasets.dataset_export import (
    DATASET_EXPORT_QUEUE_NAME,
    DatasetExportRequest,
    SqlAlchemyDatasetExporter,
    SqlAlchemyDatasetExportTaskService,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    DetectionAnnotation,
)
from backend.service.domain.tasks.yolox_task_specs import YoloXTrainingTaskSpec
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.datasets.dataset_export_queue_worker import DatasetExportQueueWorker


def test_export_dataset_generates_minimal_coco_detection_payload(tmp_path: Path) -> None:
    """验证数据集导出会生成最小 COCO detection payload。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-1",
        dataset_id="dataset-1",
        project_id="project-1",
        categories=(
            DatasetCategory(category_id=0, name="bolt"),
            DatasetCategory(category_id=1, name="nut"),
        ),
        samples=(
            DatasetSample(
                sample_id="sample-1",
                image_id=1,
                file_name="train-1.jpg",
                width=1280,
                height=720,
                split="train",
                annotations=(
                    DetectionAnnotation(
                        annotation_id="ann-1",
                        category_id=0,
                        bbox_xywh=(10.0, 20.0, 30.0, 40.0),
                    ),
                ),
            ),
            DatasetSample(
                sample_id="sample-2",
                image_id=2,
                file_name="val-1.jpg",
                width=1280,
                height=720,
                split="val",
            ),
            DatasetSample(
                sample_id="sample-3",
                image_id=3,
                file_name="test-1.jpg",
                width=1280,
                height=720,
                split="test",
            ),
        ),
    )
    exporter, dataset_storage = _create_exporter_with_storage(tmp_path, dataset_version)

    export_result = exporter.export_dataset(
        DatasetExportRequest(
            project_id="project-1",
            dataset_id="dataset-1",
            dataset_version_id="dataset-version-1",
            include_test_split=False,
        )
    )

    assert export_result.sample_count == 2
    assert export_result.split_names == ("train", "val")
    assert export_result.category_names == ("bolt", "nut")
    assert export_result.dataset_export_id is not None
    assert export_result.export_path is not None
    assert export_result.manifest_object_key == f"{export_result.export_path}/manifest.json"
    assert export_result.format_manifest is not None
    assert export_result.format_manifest.splits[0].image_root == f"{export_result.export_path}/images/train"
    assert export_result.format_manifest.splits[0].annotation_file == f"{export_result.export_path}/annotations/instances_train.json"
    train_payload = export_result.annotation_payloads_by_split["train"]
    assert train_payload.images[0].file_name == "train-1.jpg"
    assert train_payload.annotations[0].bbox_xywh == (10.0, 20.0, 30.0, 40.0)
    assert train_payload.annotations[0].area == 1200.0
    assert tuple(category.name for category in train_payload.categories) == ("bolt", "nut")

    manifest_payload = json.loads(
        dataset_storage.resolve(export_result.manifest_object_key).read_text(encoding="utf-8")
    )
    train_annotation_payload = json.loads(
        dataset_storage.resolve(
            f"{export_result.export_path}/annotations/instances_train.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest_payload["dataset_version_id"] == "dataset-version-1"
    assert train_annotation_payload["annotations"][0]["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert dataset_storage.resolve(f"{export_result.export_path}/images/train/train-1.jpg").is_file()
    assert dataset_storage.resolve(f"{export_result.export_path}/images/val/val-1.jpg").is_file()


def test_export_dataset_supports_custom_prefix_and_test_split(tmp_path: Path) -> None:
    """验证数据集导出支持自定义输出前缀并保留 test split。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-2",
        dataset_id="dataset-2",
        project_id="project-1",
        categories=(DatasetCategory(category_id=0, name="gear"),),
        samples=(
            DatasetSample(
                sample_id="sample-1",
                image_id=1,
                file_name="test-1.jpg",
                width=640,
                height=480,
                split="test",
            ),
        ),
    )
    exporter, dataset_storage = _create_exporter_with_storage(tmp_path, dataset_version)

    export_result = exporter.export_dataset(
        DatasetExportRequest(
            project_id="project-1",
            dataset_id="dataset-2",
            dataset_version_id="dataset-version-2",
            output_object_prefix="task-runs/training/task-1/dataset-export",
            include_test_split=True,
        )
    )

    assert export_result.sample_count == 1
    assert export_result.split_names == ("test",)
    assert export_result.dataset_export_id is None
    assert export_result.export_path == "task-runs/training/task-1/dataset-export"
    assert export_result.manifest_object_key == "task-runs/training/task-1/dataset-export/manifest.json"
    assert export_result.format_manifest is not None
    assert export_result.format_manifest.splits[0].annotation_file == "task-runs/training/task-1/dataset-export/annotations/instances_test.json"
    assert dataset_storage.resolve(export_result.manifest_object_key).is_file()
    assert dataset_storage.resolve("task-runs/training/task-1/dataset-export/images/test/test-1.jpg").is_file()


def test_export_dataset_generates_pascal_voc_layout_and_xml(tmp_path: Path) -> None:
    """验证数据集导出支持 Pascal VOC detection 目录与 XML。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-voc-1",
        dataset_id="dataset-voc-1",
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
                        bbox_xywh=(10.0, 20.0, 30.0, 40.0),
                    ),
                ),
            ),
        ),
    )
    exporter, dataset_storage = _create_exporter_with_storage(tmp_path, dataset_version)

    export_result = exporter.export_dataset(
        DatasetExportRequest(
            project_id="project-1",
            dataset_id="dataset-voc-1",
            dataset_version_id="dataset-version-voc-1",
            format_id=VOC_DETECTION_DATASET_FORMAT,
            include_test_split=False,
        )
    )

    assert export_result.format_id == VOC_DETECTION_DATASET_FORMAT
    assert export_result.split_names == ("train",)
    assert export_result.sample_count == 1
    assert export_result.export_path is not None
    assert export_result.format_manifest is not None

    train_payload = export_result.annotation_payloads_by_split["train"]
    assert train_payload.documents[0].file_name == "sample-1.jpg"
    assert train_payload.documents[0].annotation_relative_path == "Annotations/sample-1.xml"
    assert train_payload.documents[0].objects[0].bbox_xyxy == (10, 20, 40, 60)

    manifest_payload = json.loads(
        dataset_storage.resolve(export_result.manifest_object_key).read_text(encoding="utf-8")
    )
    annotation_xml = dataset_storage.resolve(
        f"{export_result.export_path}/Annotations/sample-1.xml"
    ).read_text(encoding="utf-8")
    image_set_file = dataset_storage.resolve(
        f"{export_result.export_path}/ImageSets/Main/train.txt"
    ).read_text(encoding="utf-8")

    assert manifest_payload["format_id"] == VOC_DETECTION_DATASET_FORMAT
    assert manifest_payload["splits"][0]["image_set_file"].endswith("/ImageSets/Main/train.txt")
    assert "<name>bolt</name>" in annotation_xml
    assert "<xmin>10</xmin>" in annotation_xml
    assert "<ymax>60</ymax>" in annotation_xml
    assert image_set_file == "sample-1\n"
    assert dataset_storage.resolve(f"{export_result.export_path}/JPEGImages/sample-1.jpg").is_file()


def test_export_dataset_rejects_supported_but_unimplemented_format() -> None:
    """验证导出器会明确拒绝当前未落地的支持格式。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-3",
        dataset_id="dataset-3",
        project_id="project-1",
        categories=(DatasetCategory(category_id=0, name="gear"),),
        samples=(),
    )
    exporter = _create_exporter_with_dataset_versions(dataset_version)

    with pytest.raises(NotImplementedError):
        exporter.export_dataset(
            DatasetExportRequest(
                project_id="project-1",
                dataset_id="dataset-3",
                dataset_version_id="dataset-version-3",
                format_id="yolo-detection-v1",
            )
        )

    assert COCO_DETECTION_DATASET_FORMAT == "coco-detection-v1"


def test_export_task_worker_persists_export_artifact_for_training_input_boundary(
    tmp_path: Path,
) -> None:
    """验证 DatasetExport 任务会把 export artifact 写成 training 唯一输入边界。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-task-1",
        dataset_id="dataset-9",
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
    export_task_service, session_factory, dataset_storage, queue_backend = (
        _create_export_task_service_with_storage(tmp_path, dataset_version)
    )
    try:
        submission = export_task_service.submit_export_task(
            DatasetExportRequest(
                project_id="project-1",
                dataset_id="dataset-9",
                dataset_version_id="dataset-version-task-1",
                format_id=COCO_DETECTION_DATASET_FORMAT,
            ),
            created_by=DEFAULT_LOCAL_AUTH_USERNAME,
        )

        queued_task = SqlAlchemyTaskService(session_factory).get_task(
            submission.task_id,
            include_events=True,
        )
        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            queued_export = unit_of_work.dataset_exports.get_dataset_export(submission.dataset_export_id)
        finally:
            unit_of_work.close()

        assert submission.queue_name == DATASET_EXPORT_QUEUE_NAME
        assert submission.status == "queued"
        assert queued_task.task.task_kind == "dataset-export"
        assert queued_task.task.state == "queued"
        assert queued_task.task.task_spec["dataset_export_id"] == submission.dataset_export_id
        assert queued_task.task.task_spec["dataset_version_id"] == "dataset-version-task-1"
        assert queued_task.task.task_spec["format_id"] == COCO_DETECTION_DATASET_FORMAT
        assert queued_task.task.result == {}
        assert queued_export is not None
        assert queued_export.status == "queued"
        assert queued_export.task_id == submission.task_id
        assert queued_export.metadata["queue_task_id"] == submission.queue_task_id

        assert _run_export_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        completed_task = SqlAlchemyTaskService(session_factory).get_task(
            submission.task_id,
            include_events=True,
        )
        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            completed_export = unit_of_work.dataset_exports.get_dataset_export(submission.dataset_export_id)
        finally:
            unit_of_work.close()

        assert completed_task.task.state == "succeeded"
        assert completed_task.task.result["dataset_id"] == "dataset-9"
        assert completed_task.task.result["dataset_version_id"] == "dataset-version-task-1"
        assert completed_task.task.result["format_id"] == COCO_DETECTION_DATASET_FORMAT
        assert completed_task.task.result["manifest_object_key"].endswith("/manifest.json")
        assert completed_task.task.result["export_path"]
        assert dataset_storage.resolve(completed_task.task.result["manifest_object_key"]).is_file()
        assert any(event.message == "dataset export completed" for event in completed_task.events)
        assert completed_export is not None
        assert completed_export.status == "completed"
        assert completed_export.manifest_object_key == completed_task.task.result["manifest_object_key"]
        assert completed_export.export_path == completed_task.task.result["export_path"]
        assert completed_export.sample_count == 1
        assert completed_export.category_names == ("bolt",)

        training_task_spec = YoloXTrainingTaskSpec(
            project_id="project-1",
            dataset_export_manifest_key=completed_task.task.result["manifest_object_key"],
            recipe_id="yolox-default",
            model_scale="s",
            output_model_name="yolox-s-bolt",
        )
        assert (
            training_task_spec.dataset_export_manifest_key
            == completed_task.task.result["manifest_object_key"]
        )
    finally:
        session_factory.engine.dispose()


def _create_exporter_with_dataset_versions(
    *dataset_versions: DatasetVersion,
) -> SqlAlchemyDatasetExporter:
    """创建写入测试数据后的 SQLAlchemy 数据集导出器。

    参数：
    - dataset_versions：初始化要写入数据库的 DatasetVersion 列表。

    返回：
    - 已写入测试数据的 SqlAlchemyDatasetExporter。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        for dataset_version in dataset_versions:
            unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    return SqlAlchemyDatasetExporter(session_factory=session_factory)


def _create_exporter_with_storage(
    tmp_path: Path,
    *dataset_versions: DatasetVersion,
) -> tuple[SqlAlchemyDatasetExporter, LocalDatasetStorage]:
    """创建同时绑定本地文件存储的 SQLAlchemy 数据集导出器。

    参数：
    - tmp_path：当前测试使用的临时目录。
    - dataset_versions：初始化要写入数据库的 DatasetVersion 列表。

    返回：
    - 已写入测试数据的 SqlAlchemyDatasetExporter 和 LocalDatasetStorage。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        for dataset_version in dataset_versions:
            unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    for dataset_version in dataset_versions:
        _seed_dataset_version_files(dataset_storage=dataset_storage, dataset_version=dataset_version)

    return (
        SqlAlchemyDatasetExporter(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ),
        dataset_storage,
    )


def _create_export_task_service_with_storage(
    tmp_path: Path,
    *dataset_versions: DatasetVersion,
) -> tuple[
    SqlAlchemyDatasetExportTaskService,
    SessionFactory,
    LocalDatasetStorage,
    LocalFileQueueBackend,
]:
    """创建绑定队列后端的 DatasetExport 任务服务。

    参数：
    - tmp_path：当前测试使用的临时目录。
    - dataset_versions：初始化要写入数据库的 DatasetVersion 列表。

    返回：
    - DatasetExport 任务服务、SessionFactory、本地文件存储与队列后端。
    """

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        for dataset_version in dataset_versions:
            unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    for dataset_version in dataset_versions:
        _seed_dataset_version_files(dataset_storage=dataset_storage, dataset_version=dataset_version)

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    return (
        SqlAlchemyDatasetExportTaskService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ),
        session_factory,
        dataset_storage,
        queue_backend,
    )


def _run_export_worker_once(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> bool:
    """执行一次 DatasetExport 队列 worker。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地数据集文件存储服务。
    - queue_backend：本地任务队列后端。

    返回：
    - 当成功处理一条导出任务时返回 True；否则返回 False。
    """

    worker = DatasetExportQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return worker.run_once()


def _seed_dataset_version_files(
    *,
    dataset_storage: LocalDatasetStorage,
    dataset_version: DatasetVersion,
) -> None:
    """为测试 DatasetVersion 写入最小图片文件。

    参数：
    - dataset_storage：本地数据集文件存储服务。
    - dataset_version：要写入文件的 DatasetVersion。
    """

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