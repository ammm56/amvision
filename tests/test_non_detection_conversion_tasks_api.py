"""non-detection conversion task API 行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.models.model_service import TrainingOutputRegistration
from backend.service.application.models.rfdetr_model_service import SqlAlchemyRfdetrModelService
from backend.service.application.models.yolo11_model_service import SqlAlchemyYolo11ModelService
from backend.service.application.models.yolo26_model_service import SqlAlchemyYolo26ModelService
from backend.service.application.models.yolov8_model_service import SqlAlchemyYoloV8ModelService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from tests.api_test_support import build_test_headers, create_api_test_context


@pytest.mark.parametrize(
    ("task_segment", "model_type", "model_service_cls"),
    [
        ("classification", "yolov8", SqlAlchemyYoloV8ModelService),
        ("segmentation", "yolo11", SqlAlchemyYolo11ModelService),
        ("pose", "yolo26", SqlAlchemyYolo26ModelService),
        ("obb", "yolov8", SqlAlchemyYoloV8ModelService),
        ("segmentation", "rfdetr", SqlAlchemyRfdetrModelService),
    ],
)
def test_create_list_detail_and_pending_result_for_non_detection_conversion_task(
    tmp_path: Path,
    task_segment: str,
    model_type: str,
    model_service_cls: type,
) -> None:
    """验证 non-detection conversion API 支持 create、list、detail 和 pending result。"""

    context = create_api_test_context(
        tmp_path,
        database_name=f"amvision-{task_segment}-{model_type}-conversion-api.db",
        enable_local_buffer_broker=False,
    )
    source_model_version_id = _seed_source_model_version(
        session_factory=context.session_factory,
        dataset_storage=context.dataset_storage,
        model_service_cls=model_service_cls,
        model_type=model_type,
        task_type=task_segment,
    )

    try:
        with context.client:
            create_response = context.client.post(
                f"/api/v1/models/{task_segment}/conversion-tasks",
                headers=_build_headers(),
                json={
                    "project_id": "project-1",
                    "model_type": model_type,
                    "source_model_version_id": source_model_version_id,
                    "target_formats": ["onnx"],
                    "runtime_profile_id": None,
                    "extra_options": {},
                    "display_name": f"{task_segment} conversion api test",
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]
            assert submission["task_type"] == task_segment
            assert submission["model_type"] == model_type
            assert submission["source_model_version_id"] == source_model_version_id
            assert submission["target_formats"] == ["onnx"]

            pending_result_response = context.client.get(
                f"/api/v1/models/{task_segment}/conversion-tasks/{task_id}/result",
                headers=_build_headers(),
            )
            assert pending_result_response.status_code == 200
            assert pending_result_response.json()["file_status"] == "pending"

            detail_response = context.client.get(
                f"/api/v1/models/{task_segment}/conversion-tasks/{task_id}?include_events=true",
                headers=_build_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "queued"
            assert detail_payload["task_type"] == task_segment
            assert detail_payload["model_type"] == model_type
            assert detail_payload["source_model_version_id"] == source_model_version_id
            assert detail_payload["target_formats"] == ["onnx"]
            assert any(event["message"].endswith("conversion queued") for event in detail_payload["events"])

            list_response = context.client.get(
                (
                    f"/api/v1/models/{task_segment}/conversion-tasks"
                    f"?project_id=project-1&source_model_version_id={source_model_version_id}"
                ),
                headers=_build_headers(),
            )
            assert list_response.status_code == 200
            list_payload = list_response.json()
            assert [item["task_id"] for item in list_payload] == [task_id]

            detection_list_response = context.client.get(
                f"/api/v1/models/detection/conversion-tasks?project_id=project-1&model_type={model_type}",
                headers=_build_headers(),
            )
            assert detection_list_response.status_code == 200
            assert detection_list_response.json() == []
    finally:
        context.session_factory.engine.dispose()


def _seed_source_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    model_service_cls: type,
    model_type: str,
    task_type: str,
) -> str:
    """写入一个用于 conversion API 测试的最小 ModelVersion。"""

    source_prefix = f"{model_type}-{task_type}-conversion-api-source"
    checkpoint_uri = f"projects/project-1/models/{source_prefix}/artifacts/checkpoints/best.pt"
    labels_uri = f"projects/project-1/models/{source_prefix}/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text(labels_uri, "ok\nng\n")
    service = model_service_cls(session_factory=session_factory)
    return service.register_training_output(
        TrainingOutputRegistration(
            project_id="project-1",
            training_task_id=f"{source_prefix}-training-task",
            model_name=f"{model_type}-{task_type}",
            model_scale="nano",
            dataset_version_id=f"{source_prefix}-dataset-version",
            checkpoint_file_id=f"{source_prefix}-checkpoint-file",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id=f"{source_prefix}-labels-file",
            labels_file_uri=labels_uri,
            task_type=task_type,
            metadata={
                "category_names": ["ok", "ng"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _build_headers() -> dict[str, str]:
    """构建 conversion API 测试请求头。"""

    return build_test_headers(scopes="models:read tasks:read tasks:write")
