"""YOLOX 评估任务 API 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import io

import cv2
from fastapi.testclient import TestClient
import numpy as np

import backend.service.application.models.yolox_evaluation_task_service as yolox_evaluation_task_service_module
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.api.app import create_app
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXTrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.evaluation.yolox_evaluation_queue_worker import YoloXEvaluationQueueWorker


def test_create_yolox_evaluation_task_and_read_report_after_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证评估任务可以创建、执行，并返回 report、per-class metrics 和结果包。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-evaluation-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-evaluation-1/manifest.json"
        ),
    )
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    worker = YoloXEvaluationQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-evaluation-worker",
    )

    def fake_run(_request):
        return yolox_evaluation_task_service_module.YoloXDetectionEvaluationResult(
            split_name="val",
            sample_count=1,
            duration_seconds=0.123,
            map50=0.88,
            map50_95=0.71,
            per_class_metrics=(
                {
                    "category_id": 0,
                    "class_index": 0,
                    "class_name": "bolt",
                    "ground_truth_count": 1,
                    "detection_count": 1,
                    "ap50": 0.88,
                    "ap50_95": 0.71,
                },
            ),
            detections=(
                {
                    "image_id": 2,
                    "category_id": 0,
                    "bbox": [12.0, 12.0, 20.0, 20.0],
                    "score": 0.91,
                },
            ),
            report_payload={
                "implementation_mode": "yolox-evaluation-minimal",
                "model_version_id": model_version_id,
                "dataset_export_id": dataset_export.dataset_export_id,
                "dataset_version_id": dataset_export.dataset_version_id,
                "dataset_export_manifest_key": dataset_export.manifest_object_key,
                "split_name": "val",
                "sample_count": 1,
                "map50": 0.88,
                "map50_95": 0.71,
                "per_class_metrics": [
                    {
                        "category_id": 0,
                        "class_index": 0,
                        "class_name": "bolt",
                        "ground_truth_count": 1,
                        "detection_count": 1,
                        "ap50": 0.88,
                        "ap50_95": 0.71,
                    }
                ],
            },
            detections_payload={
                "split_name": "val",
                "sample_count": 1,
                "detection_count": 1,
                "detections": [
                    {
                        "image_id": 2,
                        "category_id": 0,
                        "bbox": [12.0, 12.0, 20.0, 20.0],
                        "score": 0.91,
                    }
                ],
            },
        )

    monkeypatch.setattr(
        yolox_evaluation_task_service_module,
        "run_yolox_detection_evaluation",
        fake_run,
    )

    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/evaluation-tasks",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "score_threshold": 0.2,
                    "nms_threshold": 0.6,
                    "save_result_package": True,
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]

            pending_report_response = client.get(
                f"/api/v1/models/yolox/evaluation-tasks/{task_id}/report",
                headers=_build_headers(),
            )
            assert pending_report_response.status_code == 200
            assert pending_report_response.json()["file_status"] == "pending"

            assert worker.run_once() is True

            detail_response = client.get(
                f"/api/v1/models/yolox/evaluation-tasks/{task_id}",
                headers=_build_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["map50"] == 0.88
            assert detail_payload["map50_95"] == 0.71
            assert detail_payload["report_summary"]["per_class_metrics"][0]["class_name"] == "bolt"

            report_response = client.get(
                f"/api/v1/models/yolox/evaluation-tasks/{task_id}/report",
                headers=_build_headers(),
            )
            assert report_response.status_code == 200
            report_payload = report_response.json()
            assert report_payload["file_status"] == "ready"
            assert report_payload["payload"]["map50_95"] == 0.71
            assert report_payload["payload"]["per_class_metrics"][0]["ap50"] == 0.88

            output_files_response = client.get(
                f"/api/v1/models/yolox/evaluation-tasks/{task_id}/output-files",
                headers=_build_headers(),
            )
            assert output_files_response.status_code == 200
            output_files_payload = output_files_response.json()
            assert [item["file_name"] for item in output_files_payload] == [
                "report",
                "detections",
                "result-package",
            ]
            assert all(item["file_status"] == "ready" for item in output_files_payload)

            list_response = client.get(
                f"/api/v1/models/yolox/evaluation-tasks?project_id=project-1&model_version_id={model_version_id}",
                headers=_build_headers(),
            )
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert len(list_payload) == 1
            assert list_payload[0]["map50"] == 0.88
            assert list_payload[0]["report_object_key"].endswith("evaluation-report.json")

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=True)
        assert any(event.message == "yolox evaluation started" for event in task_detail.events)
        assert any(event.message == "yolox evaluation completed" for event in task_detail.events)
        assert dataset_storage.resolve(detail_payload["report_object_key"]).is_file()
        assert dataset_storage.resolve(detail_payload["detections_object_key"]).is_file()
        assert dataset_storage.resolve(detail_payload["result_package_object_key"]).is_file()
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的评估 API 测试客户端。"""

    database_path = tmp_path / "amvision-evaluation-api.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(
            enabled=False,
            max_concurrent_tasks=2,
            poll_interval_seconds=0.05,
        )
    )
    client = TestClient(
        create_app(
            settings=settings,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        )
    )
    return client, session_factory, dataset_storage, queue_backend


def _seed_completed_dataset_export(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    dataset_export_id: str,
    manifest_object_key: str,
) -> DatasetExport:
    """写入一个已完成的 DatasetExport 资源和最小 manifest 文件。"""

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
        sample_count=2,
        category_names=("bolt",),
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
            "category_names": ["bolt"],
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
                {"id": 1, "file_name": "train-1.jpg", "width": 64, "height": 64}
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
            "categories": [{"id": 0, "name": "bolt"}],
        },
    )
    dataset_storage.write_json(
        f"{export_path}/annotations/instances_val.json",
        {
            "images": [
                {"id": 2, "file_name": "val-1.jpg", "width": 64, "height": 64}
            ],
            "annotations": [
                {
                    "id": 2,
                    "image_id": 2,
                    "category_id": 0,
                    "bbox": [12, 12, 20, 20],
                    "area": 400,
                    "iscrowd": 0,
                }
            ],
            "categories": [{"id": 0, "name": "bolt"}],
        },
    )
    dataset_storage.write_bytes(f"{export_path}/images/train/train-1.jpg", _build_test_jpeg_bytes())
    dataset_storage.write_bytes(f"{export_path}/images/val/val-1.jpg", _build_test_jpeg_bytes())
    return dataset_export


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/evaluation-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/evaluation-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text(labels_uri, "bolt\n")

    model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return model_service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-evaluation-source-1",
            model_name="yolox-nano-evaluation",
            model_scale="nano",
            dataset_version_id="dataset-version-evaluation-source-1",
            checkpoint_file_id="checkpoint-file-evaluation-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-evaluation-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _build_test_jpeg_bytes() -> bytes:
    """构建一个可被 cv2 正常读取的最小 JPEG 图片。"""

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return encoded.tobytes()


def _build_headers() -> dict[str, str]:
    """构建具备评估任务所需 scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "datasets:read,models:read,tasks:read,tasks:write",
    }