"""YOLO segmentation / pose manifest 支持回归测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.contracts.datasets.exports.dataset_formats import (
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.service.application.datasets.exports import (
    DatasetExportRequest,
    SqlAlchemyDatasetExporter,
)
from backend.service.application.models.evaluation.pose_evaluation import _parse_pose_manifest
from backend.service.application.models.training.yolo_task_pose_training import (
    _load_pose_manifest,
)
from backend.service.application.models.evaluation.yolo_task_segmentation_evaluation import (
    _parse_segmentation_manifest,
)
from backend.service.application.models.training.yolo_task_segmentation_training import (
    _seg_load_manifest,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
    InstanceSegmentationAnnotation,
    PoseAnnotation,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


def test_export_dataset_writes_yolo_instance_segmentation_labels(tmp_path: Path) -> None:
    """验证 yolo-instance-seg-v1 导出写出规范的 polygon 标签。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-seg-1",
        dataset_id="dataset-seg-1",
        project_id="project-1",
        task_type="segmentation",
        categories=(DatasetCategory(category_id=0, name="part"),),
        samples=(
            DatasetSample(
                sample_id="sample-1",
                image_id=1,
                file_name="sample-1.jpg",
                width=100,
                height=50,
                split="train",
                annotations=(
                    InstanceSegmentationAnnotation(
                        annotation_id="ann-1",
                        category_id=0,
                        bbox_xywh=(10.0, 5.0, 60.0, 20.0),
                        segmentation=[[10.0, 5.0, 70.0, 5.0, 70.0, 25.0, 10.0, 25.0]],
                        area=1200.0,
                    ),
                ),
            ),
        ),
    )
    exporter, dataset_storage = _create_exporter_with_storage(tmp_path, dataset_version)

    export_result = exporter.export_dataset(
        DatasetExportRequest(
            project_id="project-1",
            dataset_id="dataset-seg-1",
            dataset_version_id="dataset-version-seg-1",
            format_id=YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            include_test_split=False,
        )
    )

    label_content = dataset_storage.resolve(
        f"{export_result.export_path}/labels/train/sample-1.txt"
    ).read_text(encoding="utf-8")
    assert (
        label_content
        == "0 0.100000 0.100000 0.700000 0.100000 0.700000 0.500000 0.100000 0.500000"
    )


def test_export_dataset_writes_yolo_pose_labels(tmp_path: Path) -> None:
    """验证 yolo-pose-v1 导出写出规范的 bbox 与关键点标签。"""

    dataset_version = DatasetVersion(
        dataset_version_id="dataset-version-pose-1",
        dataset_id="dataset-pose-1",
        project_id="project-1",
        task_type="pose",
        categories=(DatasetCategory(category_id=0, name="person"),),
        samples=(
            DatasetSample(
                sample_id="sample-1",
                image_id=1,
                file_name="sample-1.jpg",
                width=100,
                height=50,
                split="train",
                annotations=(
                    PoseAnnotation(
                        annotation_id="ann-1",
                        category_id=0,
                        bbox_xywh=(10.0, 5.0, 60.0, 20.0),
                        keypoints=[10.0, 5.0, 2.0, 70.0, 25.0, 1.0],
                        num_keypoints=2,
                        area=1200.0,
                    ),
                ),
            ),
        ),
    )
    exporter, dataset_storage = _create_exporter_with_storage(tmp_path, dataset_version)

    export_result = exporter.export_dataset(
        DatasetExportRequest(
            project_id="project-1",
            dataset_id="dataset-pose-1",
            dataset_version_id="dataset-version-pose-1",
            format_id=YOLO_POSE_DATASET_FORMAT,
            include_test_split=False,
        )
    )

    label_content = dataset_storage.resolve(
        f"{export_result.export_path}/labels/train/sample-1.txt"
    ).read_text(encoding="utf-8")
    assert (
        label_content
        == "0 0.400000 0.300000 0.600000 0.400000 0.100000 0.100000 2.000000 0.700000 0.500000 1.000000"
    )


def test_segmentation_training_manifest_supports_yolo_export(tmp_path: Path) -> None:
    """验证 segmentation 训练入口可直接解析 yolo-instance-seg-v1。"""

    storage = _seed_yolo_segmentation_storage(tmp_path)
    labels, train_annotations, val_annotations = _seg_load_manifest(
        storage,
        {
            "format_id": YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            "category_names": ["part"],
            "splits": [
                {
                    "name": "train",
                    "image_root": "exports/sample/images/train",
                    "label_root": "exports/sample/labels/train",
                },
                {
                    "name": "val",
                    "image_root": "exports/sample/images/val",
                    "label_root": "exports/sample/labels/val",
                },
            ],
        },
    )

    assert labels == ("part",)
    assert len(train_annotations) == 1
    assert train_annotations[0].class_ids == [0]
    assert train_annotations[0].boxes_xywh[0] == pytest.approx([10.0, 5.0, 60.0, 20.0])
    assert len(val_annotations) == 1


def test_segmentation_evaluation_manifest_supports_yolo_export(tmp_path: Path) -> None:
    """验证 segmentation 评估入口可直接解析 yolo-instance-seg-v1。"""

    storage = _seed_yolo_segmentation_storage(tmp_path)
    split_name, samples, label_names = _parse_segmentation_manifest(
        {
            "format_id": YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            "category_names": ["part"],
            "splits": [
                {
                    "name": "val",
                    "image_root": "exports/sample/images/val",
                    "label_root": "exports/sample/labels/val",
                }
            ],
        },
        storage,
    )

    assert split_name == "val"
    assert label_names == ("part",)
    assert len(samples) == 1
    assert samples[0]["image_path"] == "exports/sample/images/val/sample-1.jpg"
    assert samples[0]["annotations"][0]["bbox"] == pytest.approx([10.0, 5.0, 60.0, 20.0])


def test_pose_training_manifest_supports_yolo_export(tmp_path: Path) -> None:
    """验证 pose 训练入口可直接解析 yolo-pose-v1。"""

    storage = _seed_yolo_pose_storage(tmp_path)
    labels, train_annotations, val_annotations = _load_pose_manifest(
        storage,
        {
            "format_id": YOLO_POSE_DATASET_FORMAT,
            "category_names": ["person"],
            "splits": [
                {
                    "name": "train",
                    "image_root": "exports/sample/images/train",
                    "label_root": "exports/sample/labels/train",
                },
                {
                    "name": "val",
                    "image_root": "exports/sample/images/val",
                    "label_root": "exports/sample/labels/val",
                },
            ],
        },
    )

    assert labels == ("person",)
    assert len(train_annotations) == 1
    assert train_annotations[0].class_ids == [0]
    assert train_annotations[0].boxes_xywh[0] == pytest.approx([10.0, 5.0, 60.0, 20.0])
    assert train_annotations[0].keypoints == [[10.0, 5.0, 2.0, 70.0, 25.0, 1.0]]
    assert len(val_annotations) == 1


def test_pose_evaluation_manifest_supports_yolo_export(tmp_path: Path) -> None:
    """验证 pose 评估入口可直接解析 yolo-pose-v1。"""

    storage = _seed_yolo_pose_storage(tmp_path)
    split_name, samples, categories = _parse_pose_manifest(
        {
            "format_id": YOLO_POSE_DATASET_FORMAT,
            "category_names": ["person"],
            "splits": [
                {
                    "name": "val",
                    "image_root": "exports/sample/images/val",
                    "label_root": "exports/sample/labels/val",
                }
            ],
        },
        storage,
    )

    assert split_name == "val"
    assert categories == [{"id": 0, "name": "person"}]
    assert len(samples) == 1
    assert samples[0]["image_path"] == "exports/sample/images/val/sample-1.jpg"
    assert samples[0]["annotations"][0]["bbox"] == pytest.approx([10.0, 5.0, 60.0, 20.0])
    assert samples[0]["annotations"][0]["keypoints"] == [10.0, 5.0, 2.0, 70.0, 25.0, 1.0]


def _seed_yolo_segmentation_storage(tmp_path: Path) -> LocalDatasetStorage:
    """写入最小 YOLO segmentation 样本目录。"""

    storage_root = tmp_path / "dataset-storage"
    train_image_root = storage_root / "exports" / "sample" / "images" / "train"
    train_label_root = storage_root / "exports" / "sample" / "labels" / "train"
    val_image_root = storage_root / "exports" / "sample" / "images" / "val"
    val_label_root = storage_root / "exports" / "sample" / "labels" / "val"
    train_image_root.mkdir(parents=True, exist_ok=True)
    train_label_root.mkdir(parents=True, exist_ok=True)
    val_image_root.mkdir(parents=True, exist_ok=True)
    val_label_root.mkdir(parents=True, exist_ok=True)
    _write_image(train_image_root / "sample-1.jpg", width=100, height=50)
    _write_image(val_image_root / "sample-1.jpg", width=100, height=50)
    label_line = "0 0.100000 0.100000 0.700000 0.100000 0.700000 0.500000 0.100000 0.500000\n"
    (train_label_root / "sample-1.txt").write_text(label_line, encoding="utf-8")
    (val_label_root / "sample-1.txt").write_text(label_line, encoding="utf-8")
    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(storage_root)))


def _seed_yolo_pose_storage(tmp_path: Path) -> LocalDatasetStorage:
    """写入最小 YOLO pose 样本目录。"""

    storage_root = tmp_path / "dataset-storage"
    train_image_root = storage_root / "exports" / "sample" / "images" / "train"
    train_label_root = storage_root / "exports" / "sample" / "labels" / "train"
    val_image_root = storage_root / "exports" / "sample" / "images" / "val"
    val_label_root = storage_root / "exports" / "sample" / "labels" / "val"
    train_image_root.mkdir(parents=True, exist_ok=True)
    train_label_root.mkdir(parents=True, exist_ok=True)
    val_image_root.mkdir(parents=True, exist_ok=True)
    val_label_root.mkdir(parents=True, exist_ok=True)
    _write_image(train_image_root / "sample-1.jpg", width=100, height=50)
    _write_image(val_image_root / "sample-1.jpg", width=100, height=50)
    label_line = "0 0.400000 0.300000 0.600000 0.400000 0.100000 0.100000 2.000000 0.700000 0.500000 1.000000\n"
    (train_label_root / "sample-1.txt").write_text(label_line, encoding="utf-8")
    (val_label_root / "sample-1.txt").write_text(label_line, encoding="utf-8")
    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(storage_root)))


def _write_image(path: Path, *, width: int, height: int) -> None:
    """写入一张最小测试图片。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.full((height, width, 3), 120, dtype=np.uint8)
    assert cv2.imwrite(str(path), image) is True


def _create_exporter_with_storage(
    tmp_path: Path,
    *dataset_versions: DatasetVersion,
) -> tuple[SqlAlchemyDatasetExporter, LocalDatasetStorage]:
    """创建绑定本地文件存储的测试导出器。"""

    session_factory = SessionFactory(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
    Base.metadata.create_all(session_factory.engine)
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        for dataset_version in dataset_versions:
            unit_of_work.datasets.save_dataset_version(dataset_version)
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
    )
    for dataset_version in dataset_versions:
        for sample in dataset_version.samples:
            image_path = storage.resolve(
                f"projects/{dataset_version.project_id}/datasets/{dataset_version.dataset_id}/versions/"
                f"{dataset_version.dataset_version_id}/images/{sample.split}/{sample.file_name}"
            )
            _write_image(image_path, width=sample.width, height=sample.height)
    return SqlAlchemyDatasetExporter(session_factory=session_factory, dataset_storage=storage), storage
