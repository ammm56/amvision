"""YOLOX validation sessions API 行为测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import backend.service.application.models.detection_validation_session_service as validation_session_service_module
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.object_store.object_key_layout import build_public_project_file_id
from backend.service.application.runtime.detection_runtime_contracts import (
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from tests.api_test_support import build_test_headers, build_test_jpeg_bytes
from tests.yolox_test_support import (
    create_yolox_api_test_context,
    seed_yolox_model_version,
)


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
    input_uri = "projects/project-1/inputs/validation/image-1.jpg"
    dataset_storage.write_bytes(input_uri, _build_test_jpeg_bytes())

    def fake_predict(**kwargs):
        return validation_session_service_module._DetectionValidationPredictionExecution(
            detections=(
                validation_session_service_module.DetectionValidationDetection(
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
            runtime_session_info=DetectionRuntimeSessionInfo(
                backend_name="pytorch",
                model_uri=kwargs["session"].checkpoint_storage_uri,
                device_name="cpu",
                input_spec=DetectionRuntimeTensorSpec(name="images", shape=(1, 3, 64, 64), dtype="float32"),
                output_spec=DetectionRuntimeTensorSpec(name="detections", shape=(-1, 7), dtype="float32"),
                metadata={"model_version_id": kwargs["session"].model_version_id},
            ),
        )

    monkeypatch.setattr(
        validation_session_service_module.LocalDetectionValidationSessionService,
        "_run_detection_validation_prediction",
        lambda self, **kwargs: fake_predict(**kwargs),
    )

    try:
        with client:
            create_response = client.post(
                "/api/v1/models/detection/validation-sessions",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_type": "yolox",
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
                f"/api/v1/models/detection/validation-sessions/{session_id}",
                headers=_build_model_headers(),
            )
            assert detail_response.status_code == 200
            assert detail_response.json()["checkpoint_storage_uri"].endswith("best_ckpt.pth")

            predict_response = client.post(
                f"/api/v1/models/detection/validation-sessions/{session_id}/predict",
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
                f"/api/v1/models/detection/validation-sessions/{session_id}",
                headers=_build_model_headers(),
            )

        assert refreshed_detail_response.status_code == 200
        refreshed_payload = refreshed_detail_response.json()
        assert refreshed_payload["last_prediction"] is not None
        assert refreshed_payload["last_prediction"]["detection_count"] == 1
    finally:
        session_factory.engine.dispose()


def test_predict_yolox_validation_session_accepts_public_project_file_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """验证 validation session 可以直接消费 Project 公开文件 id。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    model_version_id = _seed_training_output_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    input_uri = "projects/project-1/inputs/validation/input-file-id.jpg"
    dataset_storage.write_bytes(input_uri, _build_test_jpeg_bytes())
    input_file_id = build_public_project_file_id(
        project_id="project-1",
        object_key=input_uri,
    )

    def fake_predict(**kwargs):
        return validation_session_service_module._DetectionValidationPredictionExecution(
            detections=(),
            latency_ms=5.2,
            image_width=64,
            image_height=64,
            preview_image_bytes=None,
            runtime_session_info=DetectionRuntimeSessionInfo(
                backend_name="pytorch",
                model_uri=kwargs["session"].checkpoint_storage_uri,
                device_name="cpu",
                input_spec=DetectionRuntimeTensorSpec(name="images", shape=(1, 3, 64, 64), dtype="float32"),
                output_spec=DetectionRuntimeTensorSpec(name="detections", shape=(-1, 7), dtype="float32"),
                metadata={"model_version_id": kwargs["session"].model_version_id},
            ),
        )

    monkeypatch.setattr(
        validation_session_service_module.LocalDetectionValidationSessionService,
        "_run_detection_validation_prediction",
        lambda self, **kwargs: fake_predict(**kwargs),
    )

    try:
        with client:
            create_response = client.post(
                "/api/v1/models/detection/validation-sessions",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_type": "yolox",
                    "model_version_id": model_version_id,
                },
            )
            assert create_response.status_code == 201
            session_id = create_response.json()["session_id"]

            predict_response = client.post(
                f"/api/v1/models/detection/validation-sessions/{session_id}/predict",
                headers=_build_model_headers(),
                json={
                    "input_file_id": input_file_id,
                },
            )

            detail_response = client.get(
                f"/api/v1/models/detection/validation-sessions/{session_id}",
                headers=_build_model_headers(),
            )

        assert predict_response.status_code == 200
        payload = predict_response.json()
        assert payload["input_uri"] == input_uri
        assert payload["input_file_id"] == input_file_id
        assert detail_response.status_code == 200
        assert detail_response.json()["last_prediction"]["input_file_id"] == input_file_id
    finally:
        session_factory.engine.dispose()


def test_legacy_validation_session_payload_defaults_runtime_precision(tmp_path: Path) -> None:
    """验证旧 session JSON 缺少 runtime_precision 时仍可恢复运行时快照。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    checkpoint_storage_uri = "runtime/validation-sessions/session-1/checkpoints/best_ckpt.pth"
    checkpoint_path = dataset_storage.resolve(checkpoint_storage_uri)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(b"fake-checkpoint")

    session = validation_session_service_module._build_session_from_payload(
        {
            "session_id": "validation-session-1",
            "project_id": "project-1",
            "model_type": "yolox",
            "model_id": "model-1",
            "model_version_id": "model-version-1",
            "model_name": "yolox-nano-bolt",
            "model_scale": "nano",
            "source_kind": "training-output",
            "status": "ready",
            "runtime_profile_id": None,
            "runtime_backend": "pytorch",
            "device_name": "cpu",
            "score_threshold": 0.35,
            "save_result_image": True,
            "input_size": [64, 64],
            "labels": ["bolt"],
            "checkpoint_file_id": "checkpoint-file-1",
            "checkpoint_storage_uri": checkpoint_storage_uri,
            "labels_storage_uri": None,
            "extra_options": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "tester",
            "last_prediction": None,
        }
    )

    runtime_target = validation_session_service_module._build_runtime_target_from_session(
        session=session,
        dataset_storage=dataset_storage,
    )

    assert session.runtime_precision == "fp32"
    assert runtime_target.runtime_precision == "fp32"


def _create_test_client(tmp_path: Path) -> tuple[TestClient, SessionFactory, LocalDatasetStorage]:
    """创建绑定测试数据库和本地文件存储的 validation API 客户端。"""

    context = create_yolox_api_test_context(
        tmp_path,
        database_name="amvision-validation-api.db",
        max_concurrent_tasks=1,
    )
    return context.client, context.session_factory, context.dataset_storage


def _seed_training_output_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    return seed_yolox_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        source_prefix="training-output-1",
        training_task_id="training-output-1",
        model_name="yolox-nano-bolt",
        dataset_version_id="dataset-version-1",
        checkpoint_file_id="checkpoint-file-1",
        labels_file_id="labels-file-1",
    )


def _build_test_jpeg_bytes() -> bytes:
    """构建一个可被 cv2 正常读取的最小 JPEG 图片。"""

    return build_test_jpeg_bytes()


def _build_model_headers() -> dict[str, str]:
    """构建具备 models:read scope 的测试请求头。"""

    return build_test_headers(scopes="models:read")

