"""数据集 zip 导入 API 行为测试。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.queue import LocalFileQueueBackend
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.datasets.dataset_import_queue_worker import DatasetImportQueueWorker
from backend.workers.task_manager import (
    BackgroundTaskManager,
    BackgroundTaskManagerConfig,
)
from tests.api_test_support import build_test_headers, create_api_test_context


def test_import_dataset_zip_creates_coco_dataset_version(tmp_path: Path) -> None:
    """验证导入 COCO zip 会创建 DatasetImport、DatasetVersion 和本地目录。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "received"
        assert payload["upload_state"] == "uploaded"
        assert payload["processing_state"] == "queued"
        assert payload["package_size"] > 0
        assert payload["task_id"]
        assert payload["queue_task_id"]

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "received"
        assert dataset_version is None
        assert dataset_import.metadata["task_id"] == payload["task_id"]
        assert dataset_import.metadata["upload_state"] == "uploaded"
        assert dataset_import.metadata["queue_task_id"] == payload["queue_task_id"]

        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.task_spec["dataset_import_id"] == payload["dataset_import_id"]
        assert task_detail.task.state == "queued"

        assert dataset_storage.resolve(payload["package_path"]).is_file()
        assert dataset_storage.resolve(payload["staging_path"]).is_dir()
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "coco"
        assert dataset_import.detected_profile["format_type"] == "coco"
        assert dataset_version is not None
        assert dataset_version.metadata["source_import_id"] == payload["dataset_import_id"]
        assert dataset_version.samples[0].annotations[0].bbox_xywh == (1.0, 2.0, 3.0, 4.0)
        assert dataset_version.categories[0].category_id == 0
        assert dataset_import.version_path is not None
        assert dataset_storage.resolve(dataset_import.version_path).is_dir()

        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.state == "succeeded"
        assert task_detail.task.result["dataset_version_id"] == dataset_import.dataset_version_id
        assert any(event.event_type == "result" for event in task_detail.events)

        extracted_dir = dataset_storage.resolve(payload["staging_path"])
        assert extracted_dir.is_dir()
        assert list(extracted_dir.iterdir()) == []

        sample = dataset_version.samples[0]
        sample_manifest_path = dataset_storage.resolve(
            f"{dataset_import.version_path}/samples/train/{sample.sample_id}.json"
        )
        sample_manifest = json.loads(sample_manifest_path.read_text(encoding="utf-8"))
        assert sample_manifest["image_object_key"].endswith("images/train/train-1.jpg")
        assert sample_manifest["annotations"][0]["category_id"] == 0
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_voc_dataset_version(tmp_path: Path) -> None:
    """验证导入 Pascal VOC zip 会完成 bbox 转换并写入版本目录。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-2",
                    "format_type": "voc",
                    "task_type": "detection",
                },
                files={
                    "package": ("voc-dataset.zip", _build_voc_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "received"

        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.validation_report["format_type"] == "voc"
        assert dataset_version is not None
        assert dataset_version.samples[0].annotations[0].bbox_xywh == (10.0, 20.0, 20.0, 30.0)
        assert dataset_version.categories[0].name == "bolt"

        validation_report = json.loads(
            dataset_storage.resolve(
                f"projects/project-1/datasets/dataset-2/imports/{payload['dataset_import_id']}/logs/validation-report.json"
            ).read_text(encoding="utf-8")
        )
        assert validation_report["status"] == "ok"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_auto_detects_voc_dataset_version(tmp_path: Path) -> None:
    """验证自动识别不会把 Pascal VOC 误判成 classification 数据集。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-voc-auto",
                    "task_type": "detection",
                },
                files={
                    "package": ("voc-auto-dataset.zip", _build_voc_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "voc"
        assert dataset_import.detected_profile["format_type"] == "voc"
        assert dataset_version is not None
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_accepts_nested_voc_wrapper_dirs(tmp_path: Path) -> None:
    """验证导入器可以识别带多层包裹目录和非整数标记的 Pascal VOC zip。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-3",
                    "format_type": "voc",
                    "task_type": "detection",
                },
                files={
                    "package": (
                        "voc-nested.zip",
                        _build_voc_zip_bytes(
                            with_nested_wrappers=True,
                            use_unspecified_flags=True,
                        ),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True
        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_version is not None
        assert dataset_import.format_type == "voc"
        assert dataset_import.status == "completed"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_accepts_roboflow_coco_split_layout(tmp_path: Path) -> None:
    """验证导入器可以识别 train/valid/test 目录内各自携带 manifest 的 COCO zip。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-roboflow-coco",
                    "task_type": "detection",
                },
                files={
                    "package": (
                        "roboflow-coco-dataset.zip",
                        _build_roboflow_coco_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "coco"
        assert dataset_import.detected_profile["format_type"] == "coco"
        assert dataset_import.detected_profile["split_names"] == ["train", "val", "test"]
        assert dataset_import.detected_profile["split_counts"] == {
            "train": 1,
            "val": 1,
            "test": 1,
        }
        assert dataset_import.validation_report["status"] == "ok"
        assert dataset_version is not None
        assert len(dataset_version.samples) == 3
        assert {sample.split for sample in dataset_version.samples} == {"train", "val", "test"}
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_imagenet_classification_dataset_version(tmp_path: Path) -> None:
    """验证导入 ImageNet 风格 zip 会创建 classification DatasetVersion。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-imagenet-1",
                    "format_type": "imagenet",
                    "task_type": "classification",
                },
                files={
                    "package": (
                        "imagenet-dataset.zip",
                        _build_imagenet_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.format_type == "imagenet"
        assert dataset_version is not None
        assert dataset_version.task_type == "classification"
        assert dataset_version.samples[0].annotations[0].category_id in {0, 1}
        assert dataset_import.validation_report["task_type"] == "classification"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_auto_detects_imagenet_classification_dataset_version(
    tmp_path: Path,
) -> None:
    """验证自动识别仍可正确识别 ImageNet classification 数据集。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-imagenet-auto",
                    "task_type": "classification",
                },
                files={
                    "package": (
                        "imagenet-auto-dataset.zip",
                        _build_imagenet_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "imagenet"
        assert dataset_import.detected_profile["format_type"] == "imagenet"
        assert dataset_version is not None
        assert dataset_version.task_type == "classification"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_auto_detected_imagenet_for_detection_task(
    tmp_path: Path,
) -> None:
    """验证 detection 自动识别不会接受 classification 数据集。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-imagenet-as-detection",
                    "task_type": "detection",
                },
                files={
                    "package": (
                        "imagenet-as-detection.zip",
                        _build_imagenet_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.status == "failed"
        assert dataset_import.error_message == "导入包识别结果与 task_type 不匹配"
        assert dataset_import.validation_report["status"] == "failed"
        assert dataset_import.validation_report["error"]["details"] == {
            "task_type": "detection",
            "detected_candidates": ["imagenet"],
            "supported_format_types": ["coco", "voc", "yolo"],
        }
        assert dataset_version is None
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_auto_detected_dota_for_detection_task(
    tmp_path: Path,
) -> None:
    """验证 detection 自动识别不会接受 obb 数据集。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-dota-as-detection",
                    "task_type": "detection",
                },
                files={
                    "package": (
                        "dota-as-detection.zip",
                        _build_dota_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.status == "failed"
        assert dataset_import.error_message == "导入包识别结果与 task_type 不匹配"
        assert dataset_import.validation_report["status"] == "failed"
        assert dataset_import.validation_report["error"]["details"] == {
            "task_type": "detection",
            "detected_candidates": ["dota"],
            "supported_format_types": ["coco", "voc", "yolo"],
        }
        assert dataset_version is None
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_dota_obb_dataset_version(tmp_path: Path) -> None:
    """验证导入 DOTA 风格 zip 会创建 obb DatasetVersion。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-dota-1",
                    "format_type": "dota",
                    "task_type": "obb",
                },
                files={
                    "package": (
                        "dota-dataset.zip",
                        _build_dota_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.format_type == "dota"
        assert dataset_version is not None
        assert dataset_version.task_type == "obb"
        assert dataset_version.samples[0].annotations[0].metadata["source_class_name"] == "ship"
        assert dataset_import.validation_report["task_type"] == "obb"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_yolo_detection_dataset_version(tmp_path: Path) -> None:
    """验证导入 YOLO detection zip 会创建 detection DatasetVersion。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-yolo-det-1",
                    "task_type": "detection",
                },
                files={
                    "package": (
                        "yolo-detection-dataset.zip",
                        _build_yolo_detection_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.format_type == "yolo"
        assert dataset_version is not None
        assert dataset_version.task_type == "detection"
        annotation = dataset_version.samples[0].annotations[0]
        assert round(annotation.bbox_xywh[0], 4) == 10.0
        assert round(annotation.bbox_xywh[1], 4) == 20.0
        assert round(annotation.bbox_xywh[2], 4) == 30.0
        assert round(annotation.bbox_xywh[3], 4) == 40.0
        assert dataset_version.categories[0].name == "bolt"
        assert dataset_import.validation_report["task_type"] == "detection"
    finally:
        session_factory.engine.dispose()


def test_import_yolo_dataset_uses_unwrapped_root_when_yaml_path_repeats_root_name(
    tmp_path: Path,
) -> None:
    """验证 YOLO data.yaml 的 path 与 zip 根目录同名时不会重复拼接目录。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-yolo-named-root",
                    "task_type": "detection",
                    "format_type": "yolo",
                },
                files={
                    "package": (
                        "medical-pills-like.zip",
                        _build_yolo_detection_zip_with_named_root_path_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.validation_report["split_counts"] == {"train": 1, "val": 1}
        assert dataset_version is not None
        assert len(dataset_version.samples) == 2
        assert dataset_version.categories[0].name == "pill"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_yolo_segmentation_dataset_version(tmp_path: Path) -> None:
    """验证导入 YOLO instance segmentation zip 会创建 segmentation DatasetVersion。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-yolo-seg-1",
                    "format_type": "yolo",
                    "task_type": "segmentation",
                },
                files={
                    "package": (
                        "yolo-segmentation-dataset.zip",
                        _build_yolo_segmentation_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.format_type == "yolo"
        assert dataset_version is not None
        assert dataset_version.task_type == "segmentation"
        annotation = dataset_version.samples[0].annotations[0]
        assert round(annotation.bbox_xywh[0], 4) == 10.0
        assert round(annotation.bbox_xywh[1], 4) == 20.0
        assert round(annotation.bbox_xywh[2], 4) == 30.0
        assert round(annotation.bbox_xywh[3], 4) == 40.0
        assert annotation.segmentation is not None
        assert dataset_import.validation_report["task_type"] == "segmentation"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_auto_detects_yolo_segmentation_with_test_split(
    tmp_path: Path,
) -> None:
    """验证只有 test split 的 YOLO segmentation 不会被误判为 DOTA。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-yolo-seg-test-only",
                    "task_type": "segmentation",
                },
                files={
                    "package": (
                        "yolo-segmentation-test-only.zip",
                        _build_yolo_segmentation_test_split_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "yolo"
        assert dataset_import.detected_profile["detected_candidates"] == ["yolo"]
        assert dataset_version is not None
        assert dataset_version.task_type == "segmentation"
        assert dataset_import.validation_report["split_counts"] == {"test": 1}
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_yolo_pose_dataset_version(tmp_path: Path) -> None:
    """验证导入 YOLO pose zip 会创建 pose DatasetVersion。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-yolo-pose-1",
                    "format_type": "yolo",
                    "task_type": "pose",
                },
                files={
                    "package": (
                        "yolo-pose-dataset.zip",
                        _build_yolo_pose_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.format_type == "yolo"
        assert dataset_version is not None
        assert dataset_version.task_type == "pose"
        annotation = dataset_version.samples[0].annotations[0]
        assert annotation.keypoints is not None
        assert annotation.num_keypoints == 2
        assert annotation.keypoints[:6] == [10.0, 16.0, 2.0, 40.0, 48.0, 1.0]
        assert dataset_import.validation_report["task_type"] == "pose"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_yolo_obb_dataset_version(tmp_path: Path) -> None:
    """验证导入 YOLO OBB zip 会创建 obb DatasetVersion。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-yolo-obb-1",
                    "format_type": "yolo",
                    "task_type": "obb",
                },
                files={
                    "package": (
                        "yolo-obb-dataset.zip",
                        _build_yolo_obb_zip_bytes(),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 202
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        payload = response.json()
        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
        )
        assert dataset_import is not None
        assert dataset_import.format_type == "yolo"
        assert dataset_version is not None
        assert dataset_version.task_type == "obb"
        annotation = dataset_version.samples[0].annotations[0]
        assert annotation.polygon_xy == (10.0, 10.0, 40.0, 10.0, 40.0, 30.0, 10.0, 30.0)
        assert round(annotation.bbox_xywh[0], 4) == 10.0
        assert round(annotation.bbox_xywh[1], 4) == 10.0
        assert round(annotation.bbox_xywh[2], 4) == 30.0
        assert round(annotation.bbox_xywh[3], 4) == 20.0
        assert dataset_import.validation_report["task_type"] == "obb"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_semantic_segmentation_task_type(tmp_path: Path) -> None:
    """验证导入接口当前不会把 semantic-segmentation 暴露为已实现 task type。"""

    client, session_factory, _dataset_storage, _queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-semantic-1",
                    "task_type": "semantic-segmentation",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 422
    finally:
        session_factory.engine.dispose()


def test_get_dataset_import_detail_returns_validation_report_and_version_relation(
    tmp_path: Path,
) -> None:
    """验证可以按导入记录 id 读取校验报告和关联版本摘要。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            assert create_response.status_code == 202
            dataset_import_id = create_response.json()["dataset_import_id"]

            queued_detail_response = client.get(
                f"/api/v1/datasets/imports/{dataset_import_id}",
                headers=_build_dataset_read_headers(),
            )
            assert queued_detail_response.status_code == 200
            assert queued_detail_response.json()["task_id"] is not None
            assert queued_detail_response.json()["status"] == "received"
            assert queued_detail_response.json()["processing_state"] == "queued"

            assert _run_import_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            detail_response = client.get(
                f"/api/v1/datasets/imports/{dataset_import_id}",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["dataset_import_id"] == dataset_import_id
        assert payload["task_id"] is not None
        assert payload["validation_report"]["status"] == "ok"
        assert payload["validation_report"]["warnings"] == []
        assert payload["validation_report"]["errors"] == []
        assert payload["validation_report"]["error"] is None
        assert payload["detected_profile"]["format_type"] == "coco"
        assert payload["detected_profile"]["split_counts"] == {"train": 1}
        assert payload["dataset_version"]["dataset_version_id"] == payload["dataset_version_id"]
        assert payload["dataset_version"]["sample_count"] == 1
        assert payload["dataset_version"]["category_count"] == 1
        assert payload["dataset_version"]["split_names"] == ["train"]
        assert payload["dataset_version"]["metadata"]["source_import_id"] == dataset_import_id
    finally:
        session_factory.engine.dispose()


def test_list_dataset_imports_returns_dataset_import_summaries(tmp_path: Path) -> None:
    """验证可以按 Dataset id 列出导入记录摘要。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            assert create_response.status_code == 202

            queued_list_response = client.get(
                "/api/v1/datasets/dataset-1/imports",
                headers=_build_dataset_read_headers(),
            )
            assert queued_list_response.status_code == 200
            assert queued_list_response.json()[0]["task_id"] is not None
            assert queued_list_response.json()[0]["status"] == "received"
            assert queued_list_response.json()[0]["processing_state"] == "queued"

            assert _run_import_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            list_response = client.get(
                "/api/v1/datasets/dataset-1/imports",
                headers=_build_dataset_read_headers(),
            )

        assert list_response.status_code == 200
        payload = list_response.json()
        assert len(payload) == 1
        assert payload[0]["dataset_id"] == "dataset-1"
        assert payload[0]["status"] == "completed"
        assert payload[0]["validation_status"] == "ok"
        assert payload[0]["dataset_version_id"] is not None
    finally:
        session_factory.engine.dispose()


def test_get_dataset_version_relation_returns_task_type_summary(tmp_path: Path) -> None:
    """验证可以按 DatasetVersion id 读取版本摘要。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            assert create_response.status_code == 202
            assert _run_import_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            dataset_import, _dataset_version = _load_dataset_objects(
                session_factory=session_factory,
                dataset_import_id=create_response.json()["dataset_import_id"],
            )
            dataset_version_id = dataset_import.dataset_version_id if dataset_import is not None else None
            assert dataset_version_id is not None

            detail_response = client.get(
                f"/api/v1/datasets/dataset-1/versions/{dataset_version_id}",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["dataset_version_id"] == dataset_version_id
        assert payload["dataset_id"] == "dataset-1"
        assert payload["project_id"] == "project-1"
        assert payload["task_type"] == "detection"
        assert payload["sample_count"] == 1
        assert payload["category_count"] == 1
        assert payload["split_names"] == ["train"]
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_forced_split_strategy_overrides_detected_split(tmp_path: Path) -> None:
    """验证显式 split_strategy 会覆盖导入器自动识别出的 split。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-4",
                    "task_type": "detection",
                    "split_strategy": "val",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

            assert response.status_code == 202
            assert _run_import_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True
            payload = response.json()

            detail_response = client.get(
                f"/api/v1/datasets/imports/{payload['dataset_import_id']}",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["split_strategy"] == "forced-val"
        assert detail_payload["detected_profile"]["split_names"] == ["val"]
        assert detail_payload["validation_report"]["split_counts"] == {"val": 1}
        assert detail_payload["dataset_version"]["split_names"] == ["val"]
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_invalid_split_strategy(tmp_path: Path) -> None:
    """验证非法 split_strategy 会在路由层被拒绝。"""

    client, session_factory, _dataset_storage, _queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-5",
                    "task_type": "detection",
                    "split_strategy": "shadow",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 422
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_empty_package_before_enqueue(tmp_path: Path) -> None:
    """验证空 zip 包会在提交阶段直接被拒绝，不会创建导入记录。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-empty",
                    "task_type": "detection",
                },
                files={
                    "package": ("dataset.zip", b"", "application/zip"),
                },
            )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "invalid_request"
        assert payload["error"]["message"] == "上传 zip 文件不能为空"

        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            assert unit_of_work.dataset_imports.list_dataset_imports("dataset-empty") == ()
        finally:
            unit_of_work.close()

        imports_dir = dataset_storage.resolve("projects/project-1/datasets/dataset-empty/imports")
        assert imports_dir.is_dir()
        assert list(imports_dir.iterdir()) == []
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_rejects_non_zip_payload_before_enqueue(tmp_path: Path) -> None:
    """验证伪造 zip 后缀但内容非法的文件会在提交阶段直接被拒绝。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-fake-zip",
                    "task_type": "detection",
                },
                files={
                    "package": ("dataset.zip", b"not-a-zip", "application/zip"),
                },
            )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "invalid_request"
        assert payload["error"]["message"] == "当前导入接口只接受有效的 zip 压缩包"

        unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
        try:
            assert unit_of_work.dataset_imports.list_dataset_imports("dataset-fake-zip") == ()
        finally:
            unit_of_work.close()

        imports_dir = dataset_storage.resolve("projects/project-1/datasets/dataset-fake-zip/imports")
        assert imports_dir.is_dir()
        assert list(imports_dir.iterdir()) == []
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_can_be_called_twice_for_same_dataset(tmp_path: Path) -> None:
    """验证同一 Dataset 连续导入两次不会触发样本或标注主键冲突。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            first_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-repeat",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            second_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-repeat",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert first_response.status_code == 202
        assert second_response.status_code == 202

        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True
        assert _run_import_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        first_payload = first_response.json()
        second_payload = second_response.json()
        assert first_payload["dataset_import_id"] != second_payload["dataset_import_id"]

        first_import, first_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=first_payload["dataset_import_id"],
        )
        second_import, second_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=second_payload["dataset_import_id"],
        )

        assert first_import is not None
        assert second_import is not None
        assert first_version is not None
        assert second_version is not None
        assert first_version.samples[0].sample_id != second_version.samples[0].sample_id
        assert first_version.samples[0].annotations[0].annotation_id != second_version.samples[0].annotations[0].annotation_id
    finally:
        session_factory.engine.dispose()


def test_background_task_manager_processes_multiple_dataset_import_tasks(
    tmp_path: Path,
) -> None:
    """验证后台任务管理器可以批量消费多个 DatasetImport 队列任务。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            first_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-batch-1",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            second_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-batch-2",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert first_response.status_code == 202
        assert second_response.status_code == 202

        task_manager = BackgroundTaskManager(
            consumers=(
                DatasetImportQueueWorker(
                    session_factory=session_factory,
                    dataset_storage=dataset_storage,
                    queue_backend=queue_backend,
                    worker_id="test-import-worker-batch",
                ),
            ),
            config=BackgroundTaskManagerConfig(
                max_concurrent_tasks=2,
                poll_interval_seconds=0.1,
            ),
        )

        assert task_manager.run_available_tasks() == 2

        first_import, first_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=first_response.json()["dataset_import_id"],
        )
        second_import, second_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=second_response.json()["dataset_import_id"],
        )

        assert first_import is not None
        assert second_import is not None
        assert first_import.status == "completed"
        assert second_import.status == "completed"
        assert first_version is not None
        assert second_version is not None
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_is_processed_by_independent_background_task_manager(
    tmp_path: Path,
) -> None:
    """验证独立后台任务管理器可以消费 DatasetImport 队列。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-auto-1",
                    "task_type": "detection",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

            assert response.status_code == 202
            dataset_import_id = response.json()["dataset_import_id"]

        task_manager = BackgroundTaskManager(
            consumers=(
                DatasetImportQueueWorker(
                    session_factory=session_factory,
                    dataset_storage=dataset_storage,
                    queue_backend=queue_backend,
                    worker_id="test-import-worker-auto",
                ),
            ),
            config=BackgroundTaskManagerConfig(
                max_concurrent_tasks=1,
                poll_interval_seconds=0.05,
            ),
        )
        assert task_manager.run_available_tasks() == 1

        with client:
            detail_response = client.get(
                f"/api/v1/datasets/imports/{dataset_import_id}",
                headers=_build_dataset_read_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()

        assert detail_payload is not None
        assert detail_payload["status"] == "completed"
        assert detail_payload["dataset_version_id"] is not None

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=dataset_import_id,
        )
        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_version is not None
        assert dataset_storage.resolve(dataset_import.version_path).is_dir()
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
    *,
    enable_task_manager: bool = False,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定内存 SQLite 和临时本地文件存储的测试客户端。

    参数：
    - tmp_path：当前测试使用的临时目录。

    返回：
    - TestClient、SessionFactory、LocalDatasetStorage 和 LocalFileQueueBackend。
    """

    context = create_api_test_context(
        tmp_path,
        database_name="amvision-test.db",
        enable_task_manager=enable_task_manager,
    )

    return context.client, context.session_factory, context.dataset_storage, context.queue_backend


def _load_dataset_objects(
    *,
    session_factory: SessionFactory,
    dataset_import_id: str,
    dataset_version_id: str | None = None,
) -> tuple[object | None, object | None]:
    """读取导入结果在数据库中的持久化对象。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_import_id：导入记录 id。
    - dataset_version_id：可选的版本 id；为空时自动从导入记录读取。

    返回：
    - DatasetImport 和 DatasetVersion。
    """

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)
        resolved_dataset_version_id = dataset_version_id
        if resolved_dataset_version_id is None and dataset_import is not None:
            resolved_dataset_version_id = dataset_import.dataset_version_id
        dataset_version = None
        if resolved_dataset_version_id is not None:
            dataset_version = unit_of_work.datasets.get_dataset_version(resolved_dataset_version_id)
        return dataset_import, dataset_version
    finally:
        unit_of_work.close()


def _run_import_worker_once(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> bool:
    """执行一次 DatasetImport 队列 worker。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地数据集文件存储服务。
    - queue_backend：本地任务队列后端。

    返回：
    - 当成功消费到一条任务时返回 True；否则返回 False。
    """

    worker = DatasetImportQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-import-worker",
    )
    return worker.run_once()


def _build_dataset_write_headers() -> dict[str, str]:
    """构建具备 datasets:write scope 的测试请求头。

    返回：
    - 测试请求头字典。
    """

    return build_test_headers(scopes="datasets:write")


def _build_dataset_read_headers() -> dict[str, str]:
    """构建具备 datasets:read scope 的测试请求头。

    返回：
    - 测试请求头字典。
    """

    return build_test_headers(scopes="datasets:read")


def _build_coco_zip_bytes() -> bytes:
    """构建一个最小 COCO detection zip 数据集。"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        coco_payload = {
            "images": [
                {
                    "id": 1,
                    "file_name": "train-1.jpg",
                    "width": 100,
                    "height": 80,
                }
            ],
            "annotations": [
                {
                    "id": 11,
                    "image_id": 1,
                    "category_id": 7,
                    "bbox": [1, 2, 3, 4],
                    "area": 12,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        }
        zip_file.writestr(
            "dataset-root/annotations/instances_train.json",
            json.dumps(coco_payload),
        )
        zip_file.writestr("dataset-root/train/train-1.jpg", b"fake-image")

    return buffer.getvalue()


def _build_roboflow_coco_zip_bytes() -> bytes:
    """构建一个最小 Roboflow 风格 COCO detection zip 数据集。"""

    buffer = io.BytesIO()
    split_payloads = {
        "train": {
            "images": [
                {
                    "id": 1,
                    "file_name": "train-1.jpg",
                    "width": 100,
                    "height": 80,
                }
            ],
            "annotations": [
                {
                    "id": 11,
                    "image_id": 1,
                    "category_id": 7,
                    "bbox": [1, 2, 3, 4],
                    "area": 12,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        },
        "valid": {
            "images": [
                {
                    "id": 2,
                    "file_name": "valid-1.jpg",
                    "width": 120,
                    "height": 90,
                }
            ],
            "annotations": [
                {
                    "id": 22,
                    "image_id": 2,
                    "category_id": 7,
                    "bbox": [5, 6, 7, 8],
                    "area": 56,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        },
        "test": {
            "images": [
                {
                    "id": 3,
                    "file_name": "test-1.jpg",
                    "width": 140,
                    "height": 100,
                }
            ],
            "annotations": [
                {
                    "id": 33,
                    "image_id": 3,
                    "category_id": 7,
                    "bbox": [9, 10, 11, 12],
                    "area": 132,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        },
    }

    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        for split_name, payload in split_payloads.items():
            zip_file.writestr(
                f"dataset-root/{split_name}/_annotations.coco.json",
                json.dumps(payload),
            )
            image_file_name = str(payload["images"][0]["file_name"])
            zip_file.writestr(f"dataset-root/{split_name}/{image_file_name}", b"fake-image")

    return buffer.getvalue()


def _build_voc_zip_bytes(
        *,
        with_nested_wrappers: bool = False,
        use_unspecified_flags: bool = False,
) -> bytes:
        """构建一个最小 Pascal VOC detection zip 数据集。"""

        buffer = io.BytesIO()
        truncated_value = "Unspecified" if use_unspecified_flags else "0"
        difficult_value = "Unspecified" if use_unspecified_flags else "0"
        xml_payload = """<annotation>
<folder>JPEGImages</folder>
<filename>voc-1.jpg</filename>
<size><width>120</width><height>90</height><depth>3</depth></size>
<object>
    <name>bolt</name>
    <pose>Unspecified</pose>
    <truncated>{truncated_value}</truncated>
    <difficult>{difficult_value}</difficult>
    <bndbox>
        <xmin>10</xmin>
        <ymin>20</ymin>
        <xmax>30</xmax>
        <ymax>50</ymax>
    </bndbox>
</object>
</annotation>""".format(
                truncated_value=truncated_value,
                difficult_value=difficult_value,
        )
        with zipfile.ZipFile(buffer, mode="w") as zip_file:
                prefix = "dataset-root/VOC2007/" if with_nested_wrappers else ""
                zip_file.writestr(f"{prefix}JPEGImages/voc-1.jpg", b"fake-image")
                zip_file.writestr(f"{prefix}Annotations/voc-1.xml", xml_payload)
                zip_file.writestr(f"{prefix}ImageSets/Main/train.txt", "voc-1\n")

        return buffer.getvalue()


def _build_imagenet_zip_bytes() -> bytes:
    """构建一个最小 ImageNet 风格 classification zip 数据集。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="JPEG", size=(32, 24))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr("dataset-root/train/ok/ok-1.jpg", image_bytes)
        zip_file.writestr("dataset-root/val/ng/ng-1.jpg", image_bytes)
    return buffer.getvalue()


def _build_dota_zip_bytes() -> bytes:
    """构建一个最小 DOTA 风格 OBB zip 数据集。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="PNG", size=(64, 64))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr("dataset-root/images/train/train-1.png", image_bytes)
        zip_file.writestr(
            "dataset-root/labels/train_original/train-1.txt",
            "10 10 30 10 30 30 10 30 ship 0\n",
        )
        zip_file.writestr("dataset-root/images/val/val-1.png", image_bytes)
        zip_file.writestr(
            "dataset-root/labels/val_original/val-1.txt",
            "12 12 28 12 28 28 12 28 ship 0\n",
        )
    return buffer.getvalue()


def _build_yolo_detection_zip_bytes() -> bytes:
    """构建一个最小 YOLO detection zip 数据集。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="JPEG", size=(100, 80))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr(
            "dataset-root/data.yaml",
            "\n".join(
                (
                    "path: .",
                    "train: images/train",
                    "val: images/val",
                    "names:",
                    "  0: bolt",
                )
            ),
        )
        zip_file.writestr("dataset-root/images/train/train-1.jpg", image_bytes)
        zip_file.writestr("dataset-root/labels/train/train-1.txt", "0 0.250000 0.500000 0.300000 0.500000\n")
        zip_file.writestr("dataset-root/images/val/val-1.jpg", image_bytes)
        zip_file.writestr("dataset-root/labels/val/val-1.txt", "")
    return buffer.getvalue()


def _build_yolo_detection_zip_with_named_root_path_bytes() -> bytes:
    """构建 data.yaml path 与 zip 根目录同名的 YOLO detection zip。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="JPEG", size=(100, 80))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr(
            "medical-pills/data.yaml",
            "\n".join(
                (
                    "path: medical-pills",
                    "train: images/train",
                    "val: images/val",
                    "names:",
                    "  0: pill",
                )
            ),
        )
        zip_file.writestr("medical-pills/images/train/train-1.jpg", image_bytes)
        zip_file.writestr(
            "medical-pills/labels/train/train-1.txt",
            "0 0.250000 0.500000 0.300000 0.500000\n",
        )
        zip_file.writestr("medical-pills/images/val/val-1.jpg", image_bytes)
        zip_file.writestr("medical-pills/labels/val/val-1.txt", "")
    return buffer.getvalue()


def _build_yolo_segmentation_zip_bytes() -> bytes:
    """构建一个最小 YOLO instance segmentation zip 数据集。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="PNG", size=(100, 100))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr(
            "dataset-root/data.yaml",
            "\n".join(
                (
                    "path: .",
                    "train: images/train",
                    "names:",
                    "  0: sealant",
                )
            ),
        )
        zip_file.writestr("dataset-root/images/train/train-1.png", image_bytes)
        zip_file.writestr(
            "dataset-root/labels/train/train-1.txt",
            "0 0.100000 0.200000 0.400000 0.200000 0.400000 0.600000 0.100000 0.600000\n",
        )
    return buffer.getvalue()


def _build_yolo_segmentation_test_split_zip_bytes() -> bytes:
    """构建只有 test split 的 YOLO instance segmentation zip 数据集。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="PNG", size=(512, 576))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr(
            "package-seg/package-seg.yaml",
            "\n".join(
                (
                    "path: .",
                    "test: images/test",
                    "names:",
                    "  0: package",
                )
            ),
        )
        zip_file.writestr("package-seg/images/test/test-1.png", image_bytes)
        zip_file.writestr(
            "package-seg/labels/test/test-1.txt",
            "0 0.3291015625 0.3611111109 0.2841796875 0.34375 "
            "0.23828125 0.4739583328 0.236328125 0.5225694437 "
            "0.2451171875 0.5451388890 0.2685546875 0.5659722218 "
            "0.294921875 0.5711805562 0.3203125 0.5052083328 "
            "0.34375 0.4045138890 0.333984375 0.390625 0.3291015625 0.3611111109\n",
        )
    return buffer.getvalue()


def _build_yolo_pose_zip_bytes() -> bytes:
    """构建一个最小 YOLO pose zip 数据集。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="JPEG", size=(100, 80))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr(
            "dataset-root/data.yaml",
            "\n".join(
                (
                    "path: .",
                    "train: images/train",
                    "names:",
                    "  0: person",
                    "kpt_shape: [2, 3]",
                )
            ),
        )
        zip_file.writestr("dataset-root/images/train/train-1.jpg", image_bytes)
        zip_file.writestr(
            "dataset-root/labels/train/train-1.txt",
            "0 0.250000 0.500000 0.300000 0.500000 0.100000 0.200000 2 0.400000 0.600000 1\n",
        )
    return buffer.getvalue()


def _build_yolo_obb_zip_bytes() -> bytes:
    """构建一个最小 YOLO OBB zip 数据集。"""

    buffer = io.BytesIO()
    image_bytes = _build_test_image_bytes(image_format="PNG", size=(100, 80))
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        zip_file.writestr(
            "dataset-root/data.yaml",
            "\n".join(
                (
                    "path: .",
                    "train: images/train",
                    "names:",
                    "  0: tray",
                )
            ),
        )
        zip_file.writestr("dataset-root/images/train/train-1.png", image_bytes)
        zip_file.writestr(
            "dataset-root/labels/train/train-1.txt",
            "0 0.100000 0.125000 0.400000 0.125000 0.400000 0.375000 0.100000 0.375000\n",
        )
    return buffer.getvalue()


def _build_test_image_bytes(
    *,
    image_format: str,
    size: tuple[int, int],
) -> bytes:
    """构建一张测试图片的二进制内容。"""

    image = Image.new("RGB", size, color=(120, 180, 200))
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()
