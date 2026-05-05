"""YOLOX conversion task API 行为测试。"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.models.yolox_detection_training import (
    _build_yolox_model,
    _require_training_imports,
)
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXTrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.conversion.yolox_conversion_queue_worker import YoloXConversionQueueWorker


pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
pytest.importorskip("onnxsim")


@pytest.mark.parametrize(
    (
        "create_path",
        "expected_target_formats",
        "expected_produced_formats",
        "expected_phase",
        "expected_openvino_ir_precision",
    ),
    [
        (
            "/api/v1/models/yolox/conversion-tasks/onnx",
            ["onnx"],
            ["onnx"],
            "phase-1-onnx",
            None,
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/onnx-optimized",
            ["onnx-optimized"],
            ["onnx", "onnx-optimized"],
            "phase-1-onnx",
            None,
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/openvino-ir-fp32",
            ["openvino-ir"],
            ["onnx", "onnx-optimized", "openvino-ir"],
            "phase-2-openvino-ir",
            "fp32",
        ),
        (
            "/api/v1/models/yolox/conversion-tasks/openvino-ir-fp16",
            ["openvino-ir"],
            ["onnx", "onnx-optimized", "openvino-ir"],
            "phase-2-openvino-ir",
            "fp16",
        ),
    ],
)
def test_create_yolox_conversion_task_and_read_result_after_worker(
    tmp_path: Path,
    create_path: str,
    expected_target_formats: list[str],
    expected_produced_formats: list[str],
    expected_phase: str,
    expected_openvino_ir_precision: str | None,
) -> None:
    """验证 conversion task 可以创建、执行，并返回 detail、list 和 result。"""

    if "openvino-ir" in expected_target_formats and importlib.util.find_spec("openvino") is None:
        pytest.skip("当前环境缺少 openvino，跳过 openvino-ir conversion API 测试")

    client, session_factory, dataset_storage, queue_backend = _create_test_client(tmp_path)
    source_model_version_id = _seed_real_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    worker = YoloXConversionQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id="test-yolox-conversion-worker",
    )

    try:
        with client:
            create_response = client.post(
                create_path,
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "source_model_version_id": source_model_version_id,
                    "runtime_profile_id": None,
                    "extra_options": {},
                    "display_name": "conversion api test",
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]
            assert submission["target_formats"] == expected_target_formats

            pending_result_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}/result",
                headers=_build_headers(),
            )
            assert pending_result_response.status_code == 200
            assert pending_result_response.json()["file_status"] == "pending"

            pending_detail_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}",
                headers=_build_headers(),
            )
            assert pending_detail_response.status_code == 200
            assert pending_detail_response.json()["state"] == "queued"

            assert worker.run_once() is True

            detail_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}",
                headers=_build_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["source_model_version_id"] == source_model_version_id
            assert detail_payload["requested_target_formats"] == expected_target_formats
            assert detail_payload["produced_formats"] == expected_produced_formats
            assert len(detail_payload["builds"]) == len(expected_produced_formats)
            assert detail_payload["report_summary"]["validation_summary"]["allclose"] is True
            assert detail_payload["report_summary"]["phase"] == expected_phase
            if expected_openvino_ir_precision is not None:
                assert detail_payload["report_summary"]["conversion_options"] == {
                    "openvino_ir_precision": expected_openvino_ir_precision,
                }
                openvino_builds = [
                    item for item in detail_payload["builds"] if item["build_format"] == "openvino-ir"
                ]
                assert len(openvino_builds) == 1
                assert openvino_builds[0]["metadata"]["build_precision"] == expected_openvino_ir_precision
                assert openvino_builds[0]["metadata"]["compress_to_fp16"] is (
                    expected_openvino_ir_precision == "fp16"
                )

            result_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks/{task_id}/result",
                headers=_build_headers(),
            )
            assert result_response.status_code == 200
            result_payload = result_response.json()
            assert result_payload["file_status"] == "ready"
            assert result_payload["payload"]["phase"] == expected_phase
            assert result_payload["payload"]["planned_target_formats"] == expected_target_formats
            assert result_payload["payload"]["validation_summary"]["allclose"] is True
            if expected_openvino_ir_precision is not None:
                assert result_payload["payload"]["conversion_options"] == {
                    "openvino_ir_precision": expected_openvino_ir_precision,
                }

            list_response = client.get(
                f"/api/v1/models/yolox/conversion-tasks?project_id=project-1&source_model_version_id={source_model_version_id}",
                headers=_build_headers(),
            )
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert len(list_payload) == 1
            assert list_payload[0]["produced_formats"] == expected_produced_formats

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=True)
        assert any(event.message == "yolox conversion started" for event in task_detail.events)
        assert any(event.message == "yolox conversion succeeded" for event in task_detail.events)
        assert dataset_storage.resolve(detail_payload["report_object_key"]).is_file() is True
        for build_item in detail_payload["builds"]:
            build_path = dataset_storage.resolve(build_item["build_file_uri"])
            assert build_path.is_file() is True
            if build_item["build_format"] == "openvino-ir":
                assert build_path.suffix == ".xml"
                assert build_path.with_suffix(".bin").is_file() is True
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建绑定测试数据库、本地文件存储和队列的 conversion API 测试客户端。"""

    database_path = tmp_path / "amvision-conversion-api.db"
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


def _seed_real_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带真实 checkpoint 和 labels 的最小训练输出 ModelVersion。"""

    imports = _require_training_imports()
    model = _build_yolox_model(
        imports=imports,
        model_scale="nano",
        num_classes=1,
    )
    checkpoint_buffer = io.BytesIO()
    imports.torch.save({"model": model.state_dict()}, checkpoint_buffer)

    checkpoint_uri = "projects/project-1/models/conversion-api-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/conversion-api-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, checkpoint_buffer.getvalue())
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-conversion-api-source-1",
            model_name="yolox-nano-conversion-api",
            model_scale="nano",
            dataset_version_id="dataset-version-conversion-api-source-1",
            checkpoint_file_id="checkpoint-file-conversion-api-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-conversion-api-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _build_headers() -> dict[str, str]:
    """构建 conversion API 所需请求头。"""

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,tasks:read,tasks:write",
    }