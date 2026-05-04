"""YOLOX 推理任务 API 行为测试。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.service.application.models.yolox_inference_task_service as yolox_inference_task_service_module
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXTrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.inference.yolox_inference_queue_worker import YoloXInferenceQueueWorker


def test_create_yolox_inference_task_and_read_result_after_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证正式推理任务可以创建、执行，并返回 detail 与 result。"""

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    dataset_storage.write_bytes("runtime-inputs/inference-image.jpg", b"fake-image")
    worker = YoloXInferenceQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-inference-worker",
    )

    def fake_run(**_kwargs):
        return yolox_inference_task_service_module.YoloXInferenceExecutionResult(
            detections=(
                {
                    "bbox_xyxy": [12.0, 12.0, 40.0, 40.0],
                    "score": 0.93,
                    "class_id": 0,
                    "class_name": "bolt",
                },
            ),
            latency_ms=8.5,
            image_width=64,
            image_height=64,
            preview_image_bytes=b"preview-jpg",
            runtime_session_info={
                "backend_name": "pytorch",
                "model_uri": "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth",
                "device_name": "cpu",
                "input_spec": {"name": "images", "shape": [1, 3, 64, 64], "dtype": "float32"},
                "output_spec": {"name": "detections", "shape": [-1, 7], "dtype": "float32"},
                "metadata": {"model_version_id": model_version_id},
            },
        )

    monkeypatch.setattr(
        yolox_inference_task_service_module,
        "run_yolox_inference_task",
        fake_run,
    )

    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "runtime_backend": "pytorch",
                    "device_name": "cpu",
                    "display_name": "yolox inference deployment",
                },
            )
            assert deployment_response.status_code == 201
            deployment_instance_id = deployment_response.json()["deployment_instance_id"]

            create_response = client.post(
                "/api/v1/models/yolox/inference-tasks",
                headers=_build_inference_headers(),
                json={
                    "project_id": "project-1",
                    "deployment_instance_id": deployment_instance_id,
                    "input_uri": "runtime-inputs/inference-image.jpg",
                    "score_threshold": 0.2,
                    "save_result_image": True,
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]

            task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=False)
            runtime_target_snapshot = task_detail.task.task_spec.get("runtime_target_snapshot")
            assert isinstance(runtime_target_snapshot, dict)
            assert runtime_target_snapshot["model_version_id"] == model_version_id

            def fail_if_resolve_inference_target(*_args, **_kwargs):
                raise AssertionError("worker 不应在执行阶段重新解析 deployment runtime target")

            monkeypatch.setattr(
                yolox_inference_task_service_module.SqlAlchemyYoloXDeploymentService,
                "resolve_inference_target",
                fail_if_resolve_inference_target,
            )

            pending_result_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert pending_result_response.status_code == 200
            assert pending_result_response.json()["file_status"] == "pending"

            assert worker.run_once() is True

            detail_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}",
                headers=_build_task_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["deployment_instance_id"] == deployment_instance_id
            assert detail_payload["detection_count"] == 1
            assert detail_payload["latency_ms"] == 8.5

            result_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert result_response.status_code == 200
            result_payload = result_response.json()
            assert result_payload["file_status"] == "ready"
            assert result_payload["payload"]["detections"][0]["class_name"] == "bolt"
            assert result_payload["payload"]["preview_image_uri"].endswith("preview.jpg")

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=True)
        assert any(event.message == "yolox inference started" for event in task_detail.events)
        assert any(event.message == "yolox inference completed" for event in task_detail.events)
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的 API 客户端。"""

    database_path = tmp_path / "amvision-inference-api.db"
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


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/deployment-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/deployment-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-inference-source-1",
            model_name="yolox-nano-inference",
            model_scale="nano",
            dataset_version_id="dataset-version-inference-source-1",
            checkpoint_file_id="checkpoint-file-inference-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-inference-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _build_model_headers() -> dict[str, str]:
    """构建 deployment API 所需请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,models:write",
    }


def _build_task_headers() -> dict[str, str]:
    """构建 task 读取接口请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "tasks:read",
    }


def _build_inference_headers() -> dict[str, str]:
    """构建 inference create 接口请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,tasks:write",
    }