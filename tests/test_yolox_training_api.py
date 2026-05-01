"""YOLOX 训练任务创建 API 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
import io
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import torch

from fastapi.testclient import TestClient

import backend.service.application.models.yolox_training_service as yolox_training_service_module
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.api.app import create_app
from backend.service.application.models.yolox_detection_training import (
    YoloXDetectionTrainingExecutionResult,
    YoloXTrainingEpochProgress,
    YoloXTrainingPausedError,
    YoloXTrainingSavePoint,
    _build_checkpoint_state,
    _load_resume_checkpoint,
)
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


def test_create_yolox_training_task_accepts_gpu_count_above_three(tmp_path: Path) -> None:
    """验证训练创建接口不会在提交阶段人为限制超过 3 卡的请求。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-gpu-4",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-gpu-4/manifest.json"
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
                    "output_model_name": "yolox-s-gpu4",
                    "gpu_count": 4,
                    "precision": "fp16",
                },
            )

        assert response.status_code == 202
        payload = response.json()
        task_detail = SqlAlchemyTaskService(session_factory).get_task(payload["task_id"], include_events=True)
        assert task_detail.task.task_spec["gpu_count"] == 4
        assert task_detail.task.task_spec["precision"] == "fp16"
    finally:
        session_factory.engine.dispose()


def test_create_yolox_training_task_rejects_fp8_precision(tmp_path: Path) -> None:
    """验证训练创建接口会在提交阶段拒绝当前未支持的 fp8 precision。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-fp8",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/dataset-export-training-fp8/manifest.json"
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
                    "output_model_name": "yolox-s-fp8",
                    "precision": "fp8",
                },
            )

        assert response.status_code == 422
        payload = response.json()
        assert payload["error"]["code"] == "request_validation_failed"
        assert payload["error"]["details"]["errors"]
    finally:
        session_factory.engine.dispose()


def test_create_yolox_training_task_rejects_non_positive_input_size(tmp_path: Path) -> None:
    """验证训练创建接口会拒绝非正数 input_size。"""

    client, session_factory, dataset_storage, _queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-training-bad-input-size",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-training-bad-input-size/manifest.json"
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
                    "output_model_name": "yolox-s-bad-input-size",
                    "input_size": [0, 640],
                },
            )

        assert response.status_code == 400
        payload = response.json()
        assert payload["error"]["code"] == "invalid_request"
        assert payload["error"]["message"] == "input_size 必须大于 0"
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


def test_pause_and_resume_yolox_training_task_reuses_latest_checkpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 pause 会先保存 latest checkpoint，resume 会基于该 checkpoint 继续训练。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-pause-resume-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-pause-resume-1/manifest.json"
        ),
    )
    run_count = 0
    task_id = ""

    def fake_run(request):
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            first_control = request.epoch_callback(
                _build_fake_epoch_progress(epoch=1, max_epochs=4, best_metric_value=0.21)
            )
            assert first_control is not None
            assert first_control.save_checkpoint is False
            running_train_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/train-metrics",
                headers=_build_training_headers(),
            )
            assert running_train_metrics_response.status_code == 200
            running_train_metrics_payload = running_train_metrics_response.json()
            assert running_train_metrics_payload["file_status"] == "ready"
            assert running_train_metrics_payload["task_state"] == "running"
            assert running_train_metrics_payload["payload"]["final_metrics"]["epoch"] == 1
            running_validation_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/validation-metrics",
                headers=_build_training_headers(),
            )
            assert running_validation_metrics_response.status_code == 200
            running_validation_metrics_payload = running_validation_metrics_response.json()
            assert running_validation_metrics_payload["file_status"] == "ready"
            assert running_validation_metrics_payload["task_state"] == "running"
            assert running_validation_metrics_payload["payload"]["final_metrics"]["epoch"] == 1
            pause_response = client.post(
                f"/api/v1/models/yolox/training-tasks/{task_id}/pause",
                headers=_build_training_headers(),
            )
            assert pause_response.status_code == 200
            second_control = request.epoch_callback(
                _build_fake_epoch_progress(epoch=2, max_epochs=4, best_metric_value=0.34)
            )
            assert second_control is not None
            assert second_control.save_checkpoint is True
            assert second_control.pause_training is True
            savepoint = _build_fake_savepoint(epoch=2, best_metric_value=0.34)
            assert request.savepoint_callback is not None
            request.savepoint_callback(savepoint)
            raise YoloXTrainingPausedError(savepoint)

        assert request.resume_checkpoint_path is not None
        assert request.resume_checkpoint_path.is_file()
        return _build_fake_execution_result(max_epochs=4, best_metric_value=0.48)

    monkeypatch.setattr(yolox_training_service_module, "run_yolox_detection_training", fake_run)

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
                    "output_model_name": "yolox-s-pause-resume",
                    "max_epochs": 4,
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

            paused_detail_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}",
                headers=_build_training_headers(),
            )
            assert paused_detail_response.status_code == 200
            paused_payload = paused_detail_response.json()
            assert paused_payload["state"] == "paused"
            assert paused_payload["metadata"]["training_control"]["last_save_epoch"] == 2
            assert paused_payload["latest_checkpoint_object_key"].endswith("/latest_ckpt.pth")
            assert dataset_storage.resolve(paused_payload["latest_checkpoint_object_key"]).is_file()
            paused_train_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/train-metrics",
                headers=_build_training_headers(),
            )
            assert paused_train_metrics_response.status_code == 200
            paused_train_metrics_payload = paused_train_metrics_response.json()
            assert paused_train_metrics_payload["file_status"] == "ready"
            assert paused_train_metrics_payload["task_state"] == "paused"
            assert paused_train_metrics_payload["payload"]["final_metrics"]["epoch"] == 2
            paused_validation_metrics_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}/validation-metrics",
                headers=_build_training_headers(),
            )
            assert paused_validation_metrics_response.status_code == 200
            paused_validation_metrics_payload = paused_validation_metrics_response.json()
            assert paused_validation_metrics_payload["file_status"] == "ready"
            assert paused_validation_metrics_payload["task_state"] == "paused"
            assert paused_validation_metrics_payload["payload"]["final_metrics"]["epoch"] == 2
            assert any(
                event["message"] == "yolox training checkpoint saved"
                for event in paused_payload["events"]
            )
            assert any(event["message"] == "yolox training paused" for event in paused_payload["events"])

            resume_response = client.post(
                f"/api/v1/models/yolox/training-tasks/{task_id}/resume",
                headers=_build_training_headers(),
            )
            assert resume_response.status_code == 200
            assert resume_response.json()["status"] == "queued"

            assert _run_yolox_training_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            final_detail_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}",
                headers=_build_training_headers(),
            )

        assert final_detail_response.status_code == 200
        final_payload = final_detail_response.json()
        assert final_payload["state"] == "succeeded"
        assert run_count == 2
        assert any(event["message"] == "yolox training resumed" for event in final_payload["events"])
    finally:
        session_factory.engine.dispose()


def test_resume_yolox_training_task_fails_when_validation_configuration_mismatches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 resume 后如果 latest checkpoint 的 validation 配置不一致，任务会进入 failed。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-resume-validation-mismatch-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-resume-validation-mismatch-1/manifest.json"
        ),
    )
    run_count = 0
    task_id = ""

    def fake_run(request):
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            first_control = request.epoch_callback(
                _build_fake_epoch_progress(epoch=1, max_epochs=4, best_metric_value=0.21)
            )
            assert first_control is not None
            assert first_control.save_checkpoint is False

            pause_response = client.post(
                f"/api/v1/models/yolox/training-tasks/{task_id}/pause",
                headers=_build_training_headers(),
            )
            assert pause_response.status_code == 200

            second_control = request.epoch_callback(
                _build_fake_epoch_progress(epoch=2, max_epochs=4, best_metric_value=0.34)
            )
            assert second_control is not None
            assert second_control.save_checkpoint is True
            assert second_control.pause_training is True
            savepoint = _build_fake_resume_checkpoint_savepoint(
                epoch=2,
                best_metric_value=0.34,
                input_size=(64, 64),
                evaluation_interval=5,
                validation_split_name="val",
                evaluation_confidence_threshold=0.01,
                evaluation_nms_threshold=0.65,
            )
            assert request.savepoint_callback is not None
            request.savepoint_callback(savepoint)
            raise YoloXTrainingPausedError(savepoint)

        assert request.resume_checkpoint_path is not None
        assert request.resume_checkpoint_path.is_file()
        resumed_model = torch.nn.Linear(4, 2)
        resumed_optimizer = torch.optim.SGD(resumed_model.parameters(), lr=0.01)
        _load_resume_checkpoint(
            imports=SimpleNamespace(torch=torch),
            model=resumed_model,
            optimizer=resumed_optimizer,
            checkpoint_path=request.resume_checkpoint_path,
            expected_category_names=("bolt",),
            expected_model_scale="nano",
            expected_input_size=(64, 64),
            expected_precision="fp32",
            expected_validation_split_name="val",
            expected_evaluation_interval=1,
            expected_evaluation_confidence_threshold=0.01,
            expected_evaluation_nms_threshold=0.65,
        )
        raise AssertionError("resume checkpoint 应当先因 validation 配置不一致而失败")

    monkeypatch.setattr(yolox_training_service_module, "run_yolox_detection_training", fake_run)

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
                    "output_model_name": "yolox-s-resume-validation-mismatch",
                    "max_epochs": 4,
                    "batch_size": 1,
                    "evaluation_interval": 1,
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

            resume_response = client.post(
                f"/api/v1/models/yolox/training-tasks/{task_id}/resume",
                headers=_build_training_headers(),
            )
            assert resume_response.status_code == 200
            assert resume_response.json()["status"] == "queued"

            assert _run_yolox_training_worker_once(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                queue_backend=queue_backend,
            ) is True

            detail_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}",
                headers=_build_training_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["state"] == "failed"
        assert payload["error_message"] == "resume checkpoint 的 evaluation_interval 与当前任务不一致"
        assert run_count == 2
        assert any(event["message"] == "yolox training resumed" for event in payload["events"])
        assert any(event["message"] == "yolox training failed" for event in payload["events"])
    finally:
        session_factory.engine.dispose()


def test_request_yolox_training_save_creates_manual_checkpoint_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证手动保存接口会在训练继续执行前生成一次 checkpoint saved 事件。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    dataset_export = _seed_completed_dataset_export(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        dataset_export_id="dataset-export-manual-save-1",
        manifest_object_key=(
            "projects/project-1/datasets/dataset-1/exports/"
            "dataset-export-manual-save-1/manifest.json"
        ),
    )
    task_id = ""

    def fake_run(request):
        first_control = request.epoch_callback(
            _build_fake_epoch_progress(epoch=1, max_epochs=3, best_metric_value=0.16)
        )
        assert first_control is not None
        assert first_control.save_checkpoint is False

        save_response = client.post(
            f"/api/v1/models/yolox/training-tasks/{task_id}/save",
            headers=_build_training_headers(),
        )
        assert save_response.status_code == 200

        second_control = request.epoch_callback(
            _build_fake_epoch_progress(epoch=2, max_epochs=3, best_metric_value=0.28)
        )
        assert second_control is not None
        assert second_control.save_checkpoint is True
        assert second_control.pause_training is False
        assert request.savepoint_callback is not None
        request.savepoint_callback(_build_fake_savepoint(epoch=2, best_metric_value=0.28))

        third_control = request.epoch_callback(
            _build_fake_epoch_progress(epoch=3, max_epochs=3, best_metric_value=0.42)
        )
        assert third_control is not None
        assert third_control.save_checkpoint is False
        return _build_fake_execution_result(max_epochs=3, best_metric_value=0.42)

    monkeypatch.setattr(yolox_training_service_module, "run_yolox_detection_training", fake_run)

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
                    "output_model_name": "yolox-s-manual-save",
                    "max_epochs": 3,
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

            detail_response = client.get(
                f"/api/v1/models/yolox/training-tasks/{task_id}",
                headers=_build_training_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["state"] == "succeeded"
        assert payload["metadata"]["training_control"]["last_save_epoch"] == 2
        assert any(event["message"] == "yolox training save requested" for event in payload["events"])
        assert any(event["message"] == "yolox training checkpoint saved" for event in payload["events"])
    finally:
        session_factory.engine.dispose()


def _build_fake_epoch_progress(
    *,
    epoch: int,
    max_epochs: int,
    best_metric_value: float,
) -> YoloXTrainingEpochProgress:
    """构建用于训练控制测试的最小 epoch 进度对象。"""

    return YoloXTrainingEpochProgress(
        epoch=epoch,
        max_epochs=max_epochs,
        evaluation_interval=1,
        validation_ran=True,
        evaluated_epochs=tuple(range(1, epoch + 1)),
        train_metrics={"total_loss": max(0.05, 0.8 - (0.1 * epoch)), "lr": 0.001},
        validation_metrics={"map50": best_metric_value + 0.1, "map50_95": best_metric_value},
        train_metrics_snapshot={
            "implementation_mode": "yolox-detection-minimal",
            "device": "cpu",
            "gpu_count": 0,
            "device_ids": [],
            "distributed_mode": "single-process",
            "precision": "fp32",
            "batch_size": 1,
            "max_epochs": max_epochs,
            "evaluation_interval": 1,
            "input_size": [64, 64],
            "train_split_name": "train",
            "validation_split_name": "val",
            "sample_count": 2,
            "train_sample_count": 1,
            "validation_sample_count": 1,
            "category_names": ["bolt"],
            "best_metric_name": "val_map50_95",
            "best_metric_value": best_metric_value,
            "final_metrics": {
                "epoch": epoch,
                "train_total_loss": max(0.05, 0.8 - (0.1 * epoch)),
                "val_map50": best_metric_value + 0.1,
                "val_map50_95": best_metric_value,
            },
            "epoch_history": [
                {
                    "epoch": current_epoch,
                    "train_total_loss": max(0.05, 0.8 - (0.1 * current_epoch)),
                    "val_map50": best_metric_value + 0.1,
                    "val_map50_95": best_metric_value,
                }
                for current_epoch in range(1, epoch + 1)
            ],
            "parameter_count": 123,
            "warm_start": {"enabled": False},
        },
        validation_snapshot={
            "enabled": True,
            "split_name": "val",
            "sample_count": 1,
            "evaluation_interval": 1,
            "confidence_threshold": 0.01,
            "nms_threshold": 0.65,
            "best_metric_name": "map50_95",
            "best_metric_value": best_metric_value,
            "final_metrics": {
                "epoch": epoch,
                "map50": best_metric_value + 0.1,
                "map50_95": best_metric_value,
            },
            "evaluated_epochs": list(range(1, epoch + 1)),
            "epoch_history": [
                {
                    "epoch": current_epoch,
                    "map50": best_metric_value + 0.1,
                    "map50_95": best_metric_value,
                }
                for current_epoch in range(1, epoch + 1)
            ],
        },
        current_metric_name="val_map50_95",
        current_metric_value=best_metric_value,
        best_metric_name="val_map50_95",
        best_metric_value=best_metric_value,
    )


def _build_fake_savepoint(*, epoch: int, best_metric_value: float) -> YoloXTrainingSavePoint:
    """构建用于训练控制测试的最小 savepoint。"""

    return YoloXTrainingSavePoint(
        epoch=epoch,
        latest_checkpoint_bytes=f"latest-{epoch}".encode("utf-8"),
        best_checkpoint_bytes=f"best-{epoch}".encode("utf-8"),
        best_metric_name="val_map50_95",
        best_metric_value=best_metric_value,
    )


def _build_fake_resume_checkpoint_savepoint(
    *,
    epoch: int,
    best_metric_value: float,
    input_size: tuple[int, int],
    evaluation_interval: int,
    validation_split_name: str | None,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
) -> YoloXTrainingSavePoint:
    """构建带 latest checkpoint 配置快照的 savepoint。"""

    model = torch.nn.Linear(4, 2)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    checkpoint_state = _build_checkpoint_state(
        model=model,
        optimizer=optimizer,
        epoch=epoch,
        metric_name="val_map50_95",
        metric_value=best_metric_value,
        category_names=("bolt",),
        model_scale="nano",
        input_size=input_size,
        precision="fp32",
        gpu_count=0,
        device_ids=(),
        checkpoint_kind="latest",
        validation_split_name=validation_split_name,
        evaluation_interval=evaluation_interval,
        evaluation_confidence_threshold=evaluation_confidence_threshold,
        evaluation_nms_threshold=evaluation_nms_threshold,
        epoch_history=[
            {
                "epoch": epoch,
                "train_total_loss": max(0.05, 0.8 - (0.1 * epoch)),
                "val_map50": best_metric_value + 0.1,
                "val_map50_95": best_metric_value,
            }
        ],
        validation_history=[
            {
                "epoch": epoch,
                "map50": best_metric_value + 0.1,
                "map50_95": best_metric_value,
            }
        ],
        best_metric_name="val_map50_95",
        best_metric_value=best_metric_value,
        warm_start_summary={"enabled": False},
    )
    latest_checkpoint_buffer = io.BytesIO()
    torch.save(checkpoint_state, latest_checkpoint_buffer)
    return YoloXTrainingSavePoint(
        epoch=epoch,
        latest_checkpoint_bytes=latest_checkpoint_buffer.getvalue(),
        best_checkpoint_bytes=f"best-{epoch}".encode("utf-8"),
        best_metric_name="val_map50_95",
        best_metric_value=best_metric_value,
    )


def _build_fake_execution_result(
    *,
    max_epochs: int,
    best_metric_value: float,
) -> YoloXDetectionTrainingExecutionResult:
    """构建用于训练控制测试的最小完成态训练结果。"""

    return YoloXDetectionTrainingExecutionResult(
        checkpoint_bytes=b"best-final",
        latest_checkpoint_bytes=b"latest-final",
        metrics_payload={
            "implementation_mode": "yolox-detection-minimal",
            "device": "cpu",
            "gpu_count": 0,
            "device_ids": [],
            "distributed_mode": "single-process",
            "precision": "fp32",
            "batch_size": 1,
            "max_epochs": max_epochs,
            "evaluation_interval": 1,
            "input_size": [64, 64],
            "train_split_name": "train",
            "validation_split_name": "val",
            "sample_count": 2,
            "train_sample_count": 1,
            "validation_sample_count": 1,
            "category_names": ["bolt"],
            "best_metric_name": "val_map50_95",
            "best_metric_value": best_metric_value,
            "final_metrics": {
                "epoch": max_epochs,
                "train_total_loss": 0.2,
                "val_map50": best_metric_value + 0.1,
                "val_map50_95": best_metric_value,
            },
            "epoch_history": [
                {
                    "epoch": max_epochs,
                    "train_total_loss": 0.2,
                    "val_map50": best_metric_value + 0.1,
                    "val_map50_95": best_metric_value,
                }
            ],
            "parameter_count": 123,
            "warm_start": {"enabled": False},
        },
        validation_metrics_payload={
            "enabled": True,
            "split_name": "val",
            "sample_count": 1,
            "evaluation_interval": 1,
            "confidence_threshold": 0.01,
            "nms_threshold": 0.65,
            "best_metric_name": "map50_95",
            "best_metric_value": best_metric_value,
            "final_metrics": {
                "epoch": max_epochs,
                "map50": best_metric_value + 0.1,
                "map50_95": best_metric_value,
            },
            "evaluated_epochs": list(range(1, max_epochs + 1)),
            "epoch_history": [
                {
                    "epoch": max_epochs,
                    "map50": best_metric_value + 0.1,
                    "map50_95": best_metric_value,
                }
            ],
        },
        warm_start_summary={"enabled": False},
        implementation_mode="yolox-detection-minimal",
        best_metric_name="val_map50_95",
        best_metric_value=best_metric_value,
        evaluation_interval=1,
        category_names=("bolt",),
        split_names=("train", "val"),
        sample_count=2,
        train_sample_count=1,
        input_size=(64, 64),
        batch_size=1,
        max_epochs=max_epochs,
        device="cpu",
        gpu_count=0,
        device_ids=(),
        distributed_mode="single-process",
        precision="fp32",
        validation_split_name="val",
        validation_sample_count=1,
        parameter_count=123,
    )


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