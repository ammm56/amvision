"""YOLOX 训练任务创建 API 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import cv2
import numpy as np

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.api.app import create_app
from backend.service.application.models.yolox_training_service import YOLOX_TRAINING_QUEUE_NAME
from backend.service.application.tasks.task_service import AppendTaskEventRequest, SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.training.yolox_training_queue_worker import YoloXTrainingQueueWorker


def test_create_yolox_training_task_accepts_dataset_export_id(tmp_path: Path) -> None:
    """验证训练创建接口可以直接接收 dataset_export_id。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-1/manifest.json"
        ),
    )
    try:
        with client:
            response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "s",
                    "output_model_name": "yolox-s-bolt",
                    "evaluation_interval": 3,
                    "gpu_count": 2,
                    "precision": "fp16",
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["dataset_export_id"] == dataset_export.dataset_export_id
        assert payload["dataset_export_manifest_key"] == dataset_export.manifest_object_key
        assert payload["queue_name"] == YOLOX_TRAINING_QUEUE_NAME

        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.task_kind == "yolox-training"
        assert task_detail.task.task_spec["dataset_export_id"] == dataset_export.dataset_export_id
        assert task_detail.task.task_spec["dataset_export_manifest_key"] == dataset_export.manifest_object_key
        assert task_detail.task.task_spec["manifest_object_key"] == dataset_export.manifest_object_key
        assert task_detail.task.task_spec["gpu_count"] == 2
        assert task_detail.task.task_spec["precision"] == "fp16"
        assert task_detail.task.task_spec["evaluation_interval"] == 3
        assert task_detail.task.state == "queued"
        assert any(event.message == "yolox training queued" for event in task_detail.events)

        queue_task = queue_backend.get_task(
            queue_name=YOLOX_TRAINING_QUEUE_NAME,
            task_id=payload["queue_task_id"],
        )
        assert queue_task is not None
        assert queue_task.payload["task_id"] == payload["task_id"]
    finally:
        session_factory.engine.dispose()


def test_create_yolox_training_task_accepts_manifest_key(tmp_path: Path) -> None:
    """验证训练创建接口可以通过 manifest_object_key 反查 DatasetExport。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-2",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-2/manifest.json"
        ),
    )
    try:
        with client:
            response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_manifest_key": dataset_export.manifest_object_key,
                    "recipe_id": "yolox-default",
                    "model_scale": "m",
                    "output_model_name": "yolox-m-bolt",
                },
            )

        assert response.status_code == 202
        payload = response.json()
        assert payload["dataset_export_id"] == dataset_export.dataset_export_id
        assert payload["dataset_export_manifest_key"] == dataset_export.manifest_object_key
        assert payload["dataset_version_id"] == dataset_export.dataset_version_id

        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.task_spec["evaluation_interval"] == 5
    finally:
        session_factory.engine.dispose()


def test_create_yolox_training_task_rejects_mismatched_export_id_and_manifest_key(
    tmp_path: Path,
) -> None:
    """验证当 dataset_export_id 与 manifest_object_key 不属于同一资源时接口会拒绝。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export_a = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-a",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-a/manifest.json"
        ),
    )
    dataset_export_b = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-b",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-b/manifest.json"
        ),
    )
    try:
        with client:
            response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_a.dataset_export_id,
                    "dataset_export_manifest_key": dataset_export_b.manifest_object_key,
                    "recipe_id": "yolox-default",
                    "model_scale": "s",
                    "output_model_name": "yolox-s-bolt",
                },
            )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "invalid_request"
        assert payload["error"]["message"] == "dataset_export_id 与 dataset_export_manifest_key 不属于同一个 DatasetExport"
    finally:
        session_factory.engine.dispose()


def test_list_yolox_training_tasks_filters_by_dataset_export_id(tmp_path: Path) -> None:
    """验证训练任务列表接口可以按 DatasetExport 边界筛选。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export_a = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-list-a",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-list-a/manifest.json"
        ),
    )
    dataset_export_b = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-list-b",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-list-b/manifest.json"
        ),
    )
    try:
        with client:
            create_a = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_a.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "s",
                    "output_model_name": "yolox-s-a",
                    "gpu_count": 2,
                    "precision": "fp16",
                },
            )
            create_b = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_b.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "m",
                    "output_model_name": "yolox-m-b",
                },
            )
            response = client.get(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                params={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export_a.dataset_export_id,
                },
            )

        assert create_a.status_code == 202
        assert create_b.status_code == 202
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["dataset_export_id"] == dataset_export_a.dataset_export_id
        assert payload[0]["recipe_id"] == "yolox-default"
        assert payload[0]["model_scale"] == "s"
        assert payload[0]["gpu_count"] == 2
        assert payload[0]["precision"] == "fp16"
        assert payload[0]["state"] == "queued"
        assert payload[0]["model_version_id"] is None
    finally:
        session_factory.engine.dispose()


def test_list_yolox_training_tasks_returns_top_level_model_version_id_when_completed(
    tmp_path: Path,
) -> None:
    """验证训练任务列表会把已完成任务的 model_version_id 提升到顶层字段。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-list-model-version-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-list-model-version-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "nano",
                    "output_model_name": "yolox-s-list-model-version",
                    "max_epochs": 1,
                    "batch_size": 1,
                    "precision": "fp32",
                    "input_size": [64, 64],
                },
            )

        assert create_response.status_code == 202
        assert _run_yolox_training_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        with client:
            list_response = client.get(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                params={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                },
            )

        assert list_response.status_code == 200
        payload = list_response.json()
        assert len(payload) == 1
        assert payload[0]["dataset_export_id"] == dataset_export.dataset_export_id
        assert payload[0]["state"] == "succeeded"
        assert payload[0]["model_version_id"]
        assert payload[0]["evaluation_interval"] == 5
        assert payload[0]["precision"] == "fp32"
        assert payload[0]["model_version_id"] == payload[0]["training_summary"]["model_version_id"]
    finally:
        session_factory.engine.dispose()


def test_get_yolox_training_task_detail_returns_completed_result(tmp_path: Path) -> None:
    """验证训练任务详情接口会返回完成态结果和事件流。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-detail-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-detail-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "nano",
                    "output_model_name": "yolox-s-detail",
                    "max_epochs": 1,
                    "batch_size": 1,
                    "precision": "fp32",
                    "input_size": [64, 64],
                },
            )

        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]
        assert _run_yolox_training_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        with client:
            detail_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}",
                headers=_build_training_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["task_id"] == task_id
        assert payload["state"] == "succeeded"
        assert payload["dataset_export_id"] == dataset_export.dataset_export_id
        assert payload["checkpoint_object_key"].endswith("/best_ckpt.pth")
        assert payload["latest_checkpoint_object_key"].endswith("/latest_ckpt.pth")
        assert payload["validation_metrics_object_key"].endswith("/validation-metrics.json")
        assert payload["summary_object_key"].endswith("/training-summary.json")
        assert payload["evaluation_interval"] == 5
        assert payload["precision"] == "fp32"
        assert payload["training_summary"]["implementation_mode"] == "yolox-detection-minimal"
        assert payload["training_summary"]["precision"] == "fp32"
        assert payload["training_summary"]["validation"]["enabled"] is True
        assert payload["training_summary"]["validation"]["evaluation_interval"] == 5
        assert "map50" in payload["training_summary"]["validation"]["final_metrics"]
        assert "map50_95" in payload["training_summary"]["validation"]["final_metrics"]
        assert payload["task_spec"]["manifest_object_key"] == dataset_export.manifest_object_key
        assert payload["training_summary"]["model_version_id"]
        assert payload["model_version_id"] == payload["training_summary"]["model_version_id"]
        assert "reference_code_root" not in payload["metadata"]
        assert "reference_code_root" not in payload["training_summary"]
        assert "reference_code_root" not in payload["result"].get("summary", {})
        assert any(event["message"] == "yolox training started" for event in payload["events"])
        assert any(event["message"] == "yolox training completed" for event in payload["events"])
    finally:
        session_factory.engine.dispose()


def test_get_yolox_training_validation_metrics_returns_completed_snapshot(tmp_path: Path) -> None:
    """验证可通过 HTTP 直接读取完成态训练的 validation snapshot。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-validation-metrics-detail-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-validation-metrics-detail-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "nano",
                    "output_model_name": "yolox-s-validation-metrics",
                    "max_epochs": 1,
                    "batch_size": 1,
                    "precision": "fp32",
                    "input_size": [64, 64],
                },
            )

        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]
        assert _run_yolox_training_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        with client:
            validation_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/validation-metrics",
                headers=_build_training_headers(),
            )

        assert validation_metrics_response.status_code == 200
        payload = validation_metrics_response.json()
        assert payload["file_status"] == "ready"
        assert payload["task_state"] == "succeeded"
        assert payload["object_key"].endswith("/validation-metrics.json")
        assert payload["payload"]["enabled"] is True
        assert payload["payload"]["split_name"] == "val"
        assert payload["payload"]["evaluation_interval"] == 5
        assert payload["payload"]["evaluated_epochs"] == [1]
        assert "map50" in payload["payload"]["final_metrics"]
        assert "map50_95" in payload["payload"]["final_metrics"]
        assert payload["payload"]["epoch_history"][0]["epoch"] == 1
    finally:
        session_factory.engine.dispose()


def test_get_yolox_training_train_metrics_returns_completed_snapshot(tmp_path: Path) -> None:
    """验证可通过 HTTP 直接读取完成态训练的 train metrics 快照。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-train-metrics-detail-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-train-metrics-detail-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "nano",
                    "output_model_name": "yolox-s-train-metrics",
                    "max_epochs": 1,
                    "batch_size": 1,
                    "precision": "fp32",
                    "input_size": [64, 64],
                },
            )

        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]
        assert _run_yolox_training_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        with client:
            train_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/train-metrics",
                headers=_build_training_headers(),
            )

        assert train_metrics_response.status_code == 200
        payload = train_metrics_response.json()
        assert payload["file_status"] == "ready"
        assert payload["task_state"] == "succeeded"
        assert payload["object_key"].endswith("/train-metrics.json")
        assert payload["payload"]["implementation_mode"] == "yolox-detection-minimal"
        assert payload["payload"]["evaluation_interval"] == 5
        assert isinstance(payload["payload"]["epoch_history"], list)
    finally:
        session_factory.engine.dispose()


def test_get_yolox_training_validation_metrics_returns_pending_before_snapshot_exists(
    tmp_path: Path,
) -> None:
    """验证 validation-metrics 在快照尚未生成时也返回 pending。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-validation-metrics-pending-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-validation-metrics-pending-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "nano",
                    "output_model_name": "yolox-s-validation-metrics-pending",
                },
            )

        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]

        with client:
            validation_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/validation-metrics",
                headers=_build_training_headers(),
            )

        assert validation_metrics_response.status_code == 200
        payload = validation_metrics_response.json()
        assert payload["file_status"] == "pending"
        assert payload["task_state"] == "queued"
        assert payload["object_key"] is None
        assert payload["payload"] == {}
    finally:
        session_factory.engine.dispose()


def test_get_yolox_training_task_detail_exposes_output_prefix_while_running(tmp_path: Path) -> None:
    """验证 running 阶段也会把 output_object_prefix 提升到顶层响应。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-running-output-prefix-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-running-output-prefix-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "nano",
                    "output_model_name": "yolox-s-running-prefix",
                    "gpu_count": 1,
                    "precision": "fp16",
                },
            )

        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]
        output_object_prefix = f"task-runs/training/{task_id}"
        validation_metrics_object_key = (
            f"{output_object_prefix}/artifacts/reports/validation-metrics.json"
        )
        dataset_storage.write_json(
            validation_metrics_object_key,
            {
                "enabled": True,
                "split_name": "val",
                "sample_count": 1,
                "evaluation_interval": 5,
                "confidence_threshold": 0.01,
                "nms_threshold": 0.65,
                "best_metric_name": "map50_95",
                "best_metric_value": 0.41,
                "final_metrics": {"epoch": 5, "map50": 0.62, "map50_95": 0.41},
                "evaluated_epochs": [5],
                "epoch_history": [
                    {"epoch": 5, "map50": 0.62, "map50_95": 0.41}
                ],
            },
        )
        SqlAlchemyTaskService(session_factory).append_task_event(
            AppendTaskEventRequest(
                task_id=task_id,
                event_type="status",
                message="yolox training started",
                payload={
                    "state": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "attempt_no": 1,
                    "progress": {
                        "stage": "training",
                        "percent": 50,
                        "epoch": 5,
                        "max_epochs": 10,
                        "evaluation_interval": 5,
                        "validation_ran": True,
                        "evaluated_epochs": [5],
                        "current_metric_name": "val_map50_95",
                        "current_metric_value": 0.41,
                        "best_metric_name": "val_map50_95",
                        "best_metric_value": 0.41,
                        "train_metrics": {"total_loss": 0.8, "lr": 0.001},
                        "validation_metrics": {"map50": 0.62, "map50_95": 0.41},
                    },
                    "metadata": {
                        "runner_mode": "yolox-detection-minimal",
                        "output_object_prefix": output_object_prefix,
                        "validation_metrics_object_key": validation_metrics_object_key,
                        "requested_precision": "fp16",
                        "requested_gpu_count": 1,
                    },
                    "result": {
                        "output_object_prefix": output_object_prefix,
                        "validation_metrics_object_key": validation_metrics_object_key,
                    },
                },
            )
        )

        with client:
            detail_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}",
                headers=_build_training_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["state"] == "running"
        assert payload["output_object_prefix"] == output_object_prefix
        assert payload["validation_metrics_object_key"] == validation_metrics_object_key
        assert payload["progress"]["validation_ran"] is True
        assert payload["progress"]["evaluated_epochs"] == [5]
        assert payload["progress"]["validation_metrics"]["map50"] == 0.62
        assert payload["progress"]["validation_metrics"]["map50_95"] == 0.41
        assert payload["checkpoint_object_key"] is None

        with client:
            validation_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/validation-metrics",
                headers=_build_training_headers(),
            )

        assert validation_metrics_response.status_code == 200
        validation_metrics_payload = validation_metrics_response.json()
        assert validation_metrics_payload["file_status"] == "ready"
        assert validation_metrics_payload["task_state"] == "running"
        assert validation_metrics_payload["object_key"] == validation_metrics_object_key
        assert validation_metrics_payload["payload"]["evaluated_epochs"] == [5]
        assert validation_metrics_payload["payload"]["final_metrics"]["map50"] == 0.62
        assert validation_metrics_payload["payload"]["final_metrics"]["map50_95"] == 0.41

        with client:
            train_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/train-metrics",
                headers=_build_training_headers(),
            )

        assert train_metrics_response.status_code == 200
        train_metrics_payload = train_metrics_response.json()
        assert train_metrics_payload["file_status"] == "pending"
        assert train_metrics_payload["task_state"] == "running"
        assert train_metrics_payload["object_key"].endswith("/train-metrics.json")
        assert train_metrics_payload["payload"] == {}
    finally:
        session_factory.engine.dispose()


def test_get_yolox_training_output_files_returns_completed_entries(tmp_path: Path) -> None:
    """验证 output-files 资源组会统一公开训练输出文件状态和可读内容。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-output-files-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-output-files-1/manifest.json"
        ),
    )
    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/training-tasks",
                headers=_build_training_headers(),
                json={
                    "project_id": "project-1",
                    "dataset_export_id": dataset_export.dataset_export_id,
                    "recipe_id": "yolox-default",
                    "model_scale": "nano",
                    "output_model_name": "yolox-s-output-files",
                    "max_epochs": 1,
                    "batch_size": 1,
                    "precision": "fp32",
                    "input_size": [64, 64],
                },
            )

        assert create_response.status_code == 202
        task_id = create_response.json()["task_id"]
        assert _run_yolox_training_worker_once(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
        ) is True

        with client:
            output_files_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/output-files",
                headers=_build_training_headers(),
            )

        assert output_files_response.status_code == 200
        output_files_payload = output_files_response.json()
        assert len(output_files_payload) == 6
        output_files_by_name = {
            item["file_name"]: item
            for item in output_files_payload
        }
        assert output_files_by_name["summary"]["file_status"] == "ready"
        assert output_files_by_name["labels"]["file_kind"] == "text"
        assert output_files_by_name["best-checkpoint"]["file_kind"] == "checkpoint"
        assert output_files_by_name["latest-checkpoint"]["file_status"] == "ready"

        with client:
            summary_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/output-files/summary",
                headers=_build_training_headers(),
            )
            labels_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/output-files/labels",
                headers=_build_training_headers(),
            )
            checkpoint_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/output-files/best-checkpoint",
                headers=_build_training_headers(),
            )

        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        assert summary_payload["file_status"] == "ready"
        assert summary_payload["payload"]["implementation_mode"] == "yolox-detection-minimal"

        assert labels_response.status_code == 200
        labels_payload = labels_response.json()
        assert labels_payload["file_status"] == "ready"
        assert labels_payload["text_content"] == "bolt\n"
        assert labels_payload["lines"] == ["bolt"]

        assert checkpoint_response.status_code == 200
        checkpoint_payload = checkpoint_response.json()
        assert checkpoint_payload["file_status"] == "ready"
        assert checkpoint_payload["size_bytes"] > 0
        assert checkpoint_payload["payload"] == {}
        assert checkpoint_payload["text_content"] is None
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的训练 API 测试客户端。"""

    database_path = tmp_path / "amvision-training-api.db"
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
        split_names=("train",),
        sample_count=1,
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
                }
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
            "categories": [{"id": 0, "name": "bolt"}],
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
                    "category_id": 0,
                    "bbox": [12, 12, 20, 20],
                    "area": 400,
                    "iscrowd": 0,
                }
            ],
            "categories": [{"id": 0, "name": "bolt"}],
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


def _build_training_headers() -> dict[str, str]:
    """构建具备训练创建所需 scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "datasets:read,tasks:read,tasks:write",
    }


def _run_yolox_training_worker_once(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_backend: LocalFileQueueBackend,
) -> bool:
    """执行一次 YOLOX 训练队列 worker。"""

    worker = YoloXTrainingQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-training-worker",
    )
    return worker.run_once()