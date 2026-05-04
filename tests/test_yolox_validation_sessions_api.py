"""YOLOX validation sessions API 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

import backend.service.application.models.yolox_validation_session_service as validation_session_service_module
from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXTrainingOutputRegistration,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.shared.yolox_runtime_contracts import RuntimeTensorSpec, YoloXRuntimeSessionInfo


def test_create_and_predict_yolox_validation_session_returns_prediction_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 validation session 可以创建、查询并返回单图预测结果。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_training_output_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    input_uri = "validation-inputs/image-1.jpg"
    dataset_storage.write_bytes(input_uri, _build_test_jpeg_bytes())

    def fake_predict(**kwargs):
        return validation_session_service_module._YoloXValidationPredictionExecution(
            detections=(
                validation_session_service_module.YoloXValidationDetection(
                    bbox_xyxy=(8.0, 10.0, 28.0, 30.0),
                    score=0.91,
                    class_id=0,
                    class_name="bolt",
                ),
            ),
            latency_ms=6.8,
            image_width=64,
            image_height=64,
            preview_image_bytes=_build_test_jpeg_bytes(),
            runtime_session_info=YoloXRuntimeSessionInfo(
                backend_name="pytorch",
                model_uri=kwargs["session"].checkpoint_storage_uri,
                device_name="cpu",
                input_spec=RuntimeTensorSpec(name="images", shape=(1, 3, 64, 64), dtype="float32"),
                output_spec=RuntimeTensorSpec(name="detections", shape=(-1, 7), dtype="float32"),
                metadata={"model_version_id": kwargs["session"].model_version_id},
            ),
        )

    monkeypatch.setattr(
        validation_session_service_module,
        "_run_yolox_validation_prediction",
        fake_predict,
    )

    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/validation-sessions",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                    "runtime_backend": "pytorch",
                    "device_name": "cpu",
                    "score_threshold": 0.35,
                    "save_result_image": True,
                },
            )
            assert create_response.status_code == 201
            create_payload = create_response.json()
            assert create_payload["status"] == "ready"
            assert create_payload["labels"] == ["bolt"]
            assert create_payload["last_prediction"] is None

            session_id = create_payload["session_id"]
            detail_response = client.get(
                f"/api/v1/models/yolox/validation-sessions/{session_id}",
                headers=_build_model_headers(),
            )
            assert detail_response.status_code == 200
            assert detail_response.json()["checkpoint_storage_uri"].endswith("best_ckpt.pth")

            predict_response = client.post(
                f"/api/v1/models/yolox/validation-sessions/{session_id}/predict",
                headers=_build_model_headers(),
                json={
                    "input_uri": input_uri,
                },
            )

            assert predict_response.status_code == 200
            predict_payload = predict_response.json()
            assert predict_payload["detections"][0]["class_name"] == "bolt"
            assert predict_payload["preview_image_uri"].endswith("preview.jpg")
            assert predict_payload["raw_result_uri"].endswith("raw-result.json")
            assert predict_payload["runtime_session_info"]["backend_name"] == "pytorch"

            refreshed_detail_response = client.get(
                f"/api/v1/models/yolox/validation-sessions/{session_id}",
                headers=_build_model_headers(),
            )

        assert refreshed_detail_response.status_code == 200
        refreshed_payload = refreshed_detail_response.json()
        assert refreshed_payload["last_prediction"] is not None
        assert refreshed_payload["last_prediction"]["detection_count"] == 1
    finally:
        session_factory.engine.dispose()


def test_predict_yolox_validation_session_rejects_input_file_id(tmp_path: Path) -> None:
    """验证最小 validation session 会显式拒绝尚未支持的 input_file_id。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_training_output_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )

    try:
        with client:
            create_response = client.post(
                "/api/v1/models/yolox/validation-sessions",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_version_id": model_version_id,
                },
            )
            assert create_response.status_code == 201
            session_id = create_response.json()["session_id"]

            predict_response = client.post(
                f"/api/v1/models/yolox/validation-sessions/{session_id}/predict",
                headers=_build_model_headers(),
                json={
                    "input_file_id": "input-file-1",
                },
            )

        assert predict_response.status_code == 400
        payload = predict_response.json()
        assert payload["error"]["code"] == "invalid_request"
    finally:
        session_factory.engine.dispose()


def _create_test_client(tmp_path: Path) -> tuple[TestClient, SessionFactory, LocalDatasetStorage]:
    """创建绑定测试数据库和本地文件存储的 validation API 客户端。"""

    database_path = tmp_path / "amvision-validation-api.db"
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
            max_concurrent_tasks=1,
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
    return client, session_factory, dataset_storage


def _seed_training_output_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    checkpoint_uri = "projects/project-1/models/training-output-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/training-output-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-output-1",
            model_name="yolox-nano-bolt",
            model_scale="nano",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="checkpoint-file-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-1",
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


def _build_model_headers() -> dict[str, str]:
    """构建具备 models:read scope 的测试请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read",
    }