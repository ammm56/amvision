"""非 detection 推理与 deployment API 最小回归。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11TrainingOutputRegistration,
)
from backend.service.application.models.inference.classification_inference_task_service import (
    SqlAlchemyClassificationInferenceTaskService,
)
from backend.service.application.models.inference.obb_inference_task_service import (
    SqlAlchemyObbInferenceTaskService,
)
from backend.service.application.models.inference.pose_inference_task_service import (
    SqlAlchemyPoseInferenceTaskService,
)
from backend.service.application.models.inference.segmentation_inference_task_service import (
    SqlAlchemySegmentationInferenceTaskService,
)
from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
    Yolo26TrainingOutputRegistration,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8TrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from tests.api_test_support import build_test_headers, create_api_test_context
from tests.yolox_test_support import FakeDeploymentProcessSupervisor


_PROJECT_INPUT_URI = "projects/project-1/inputs/inference/non-detection-input.jpg"


@dataclass(frozen=True)
class _TaskTypeApiSpec:
    """描述单个非 detection task type 的 API 测试规格。"""

    task_type: str
    model_type: str
    model_service_cls: type
    output_registration_cls: type
    inference_task_service_cls: type


_TASK_SPECS = (
    _TaskTypeApiSpec(
        task_type="classification",
        model_type="yolo11",
        model_service_cls=SqlAlchemyYolo11ModelService,
        output_registration_cls=Yolo11TrainingOutputRegistration,
        inference_task_service_cls=SqlAlchemyClassificationInferenceTaskService,
    ),
    _TaskTypeApiSpec(
        task_type="segmentation",
        model_type="yolo26",
        model_service_cls=SqlAlchemyYolo26ModelService,
        output_registration_cls=Yolo26TrainingOutputRegistration,
        inference_task_service_cls=SqlAlchemySegmentationInferenceTaskService,
    ),
    _TaskTypeApiSpec(
        task_type="pose",
        model_type="yolov8",
        model_service_cls=SqlAlchemyYoloV8ModelService,
        output_registration_cls=YoloV8TrainingOutputRegistration,
        inference_task_service_cls=SqlAlchemyPoseInferenceTaskService,
    ),
    _TaskTypeApiSpec(
        task_type="obb",
        model_type="yolo26",
        model_service_cls=SqlAlchemyYolo26ModelService,
        output_registration_cls=Yolo26TrainingOutputRegistration,
        inference_task_service_cls=SqlAlchemyObbInferenceTaskService,
    ),
)


@pytest.mark.parametrize("spec", _TASK_SPECS, ids=lambda item: item.task_type)
def test_non_detection_async_inference_task_requires_running_process_and_persists_owner_id(
    tmp_path: Path,
    spec: _TaskTypeApiSpec,
) -> None:
    """验证非 detection inference task 会执行 async 前检查，并写入 owner id。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path, task_type=spec.task_type)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        spec=spec,
    )
    dataset_storage.write_bytes(_PROJECT_INPUT_URI, b"fake-image")

    try:
        with client:
            deployment_instance_id = _create_deployment_instance(
                client=client,
                spec=spec,
                model_version_id=model_version_id,
            )

            create_response = client.post(
                f"/api/v1/models/{spec.task_type}/inference-tasks",
                headers=_build_inference_headers(),
                json={
                    "project_id": "project-1",
                    "deployment_instance_id": deployment_instance_id,
                    "model_type": spec.model_type,
                    "input_uri": _PROJECT_INPUT_URI,
                },
            )
            assert create_response.status_code == 400
            error_payload = create_response.json()["error"]
            assert error_payload["code"] == "invalid_request"
            assert error_payload["details"]["runtime_mode"] == "async"

            start_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_model_headers(),
            )
            assert start_response.status_code == 200
            assert start_response.json()["process_state"] == "running"

            create_after_start_response = client.post(
                f"/api/v1/models/{spec.task_type}/inference-tasks",
                headers=_build_inference_headers(),
                json={
                    "project_id": "project-1",
                    "deployment_instance_id": deployment_instance_id,
                    "model_type": spec.model_type,
                    "input_uri": _PROJECT_INPUT_URI,
                },
            )
            assert create_after_start_response.status_code == 202
            task_id = create_after_start_response.json()["task_id"]

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=False)
        assert (
            task_detail.task.task_spec["async_inference_owner_id"]
            == getattr(client.app.state, f"{spec.task_type}_async_inference_service_id")
        )
        assert task_detail.task.task_spec["runtime_target_snapshot"]["task_type"] == spec.task_type
        assert task_detail.task.task_spec["runtime_target_snapshot"]["model_type"] == spec.model_type
    finally:
        session_factory.engine.dispose()


@pytest.mark.parametrize("spec", _TASK_SPECS, ids=lambda item: item.task_type)
def test_non_detection_deployment_runtime_controls_cover_sync_and_async_basics(
    tmp_path: Path,
    spec: _TaskTypeApiSpec,
) -> None:
    """验证非 detection deployment 控制面已经具备最小 sync/async 基础动作。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path, task_type=spec.task_type)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        spec=spec,
    )

    try:
        with client:
            deployment_instance_id = _create_deployment_instance(
                client=client,
                spec=spec,
                model_version_id=model_version_id,
            )

            sync_status_before_response = client.get(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/sync/status",
                headers=_build_model_headers(),
            )
            assert sync_status_before_response.status_code == 200
            assert sync_status_before_response.json()["process_state"] == "stopped"

            sync_warmup_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/sync/warmup",
                headers=_build_model_headers(),
            )
            assert sync_warmup_response.status_code == 200
            sync_warmup_payload = sync_warmup_response.json()
            assert sync_warmup_payload["runtime_mode"] == "sync"
            assert sync_warmup_payload["healthy_instance_count"] == 1
            assert sync_warmup_payload["warmed_instance_count"] == 1

            sync_events_response = client.get(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/events?runtime_mode=sync",
                headers=_build_model_headers(),
            )
            assert sync_events_response.status_code == 200
            assert [item["event_type"] for item in sync_events_response.json()] == [
                "deployment.started",
                "deployment.warmup.completed",
            ]
            assert all(item["runtime_mode"] == "sync" for item in sync_events_response.json())

            sync_reset_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/sync/reset",
                headers=_build_model_headers(),
            )
            assert sync_reset_response.status_code == 200
            assert sync_reset_response.json()["warmed_instance_count"] == 0

            async_start_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_model_headers(),
            )
            assert async_start_response.status_code == 200
            assert async_start_response.json()["process_state"] == "running"

            async_status_response = client.get(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/async/status",
                headers=_build_model_headers(),
            )
            assert async_status_response.status_code == 200
            assert async_status_response.json()["process_state"] == "running"

            async_events_response = client.get(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/events?runtime_mode=async",
                headers=_build_model_headers(),
            )
            assert async_events_response.status_code == 200
            assert [item["event_type"] for item in async_events_response.json()] == ["deployment.started"]

            async_stop_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/async/stop",
                headers=_build_model_headers(),
            )
            assert async_stop_response.status_code == 200
            assert async_stop_response.json()["process_state"] == "stopped"
    finally:
        session_factory.engine.dispose()


@pytest.mark.parametrize("spec", _TASK_SPECS, ids=lambda item: item.task_type)
def test_non_detection_sync_infer_returns_task_native_payload(
    tmp_path: Path,
    spec: _TaskTypeApiSpec,
) -> None:
    """验证非 detection sync /infer 会返回各自 task-native 结果载荷。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path, task_type=spec.task_type)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        spec=spec,
    )
    dataset_storage.write_bytes(_PROJECT_INPUT_URI, b"fake-image")

    try:
        with client:
            deployment_instance_id = _create_deployment_instance(
                client=client,
                spec=spec,
                model_version_id=model_version_id,
            )

            start_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/sync/start",
                headers=_build_model_headers(),
            )
            assert start_response.status_code == 200
            assert start_response.json()["process_state"] == "running"

            infer_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/infer",
                headers=_build_model_headers(),
                json=_build_direct_infer_payload(spec),
            )
            assert infer_response.status_code == 200
            payload = infer_response.json()
            assert payload["deployment_instance_id"] == deployment_instance_id
            assert payload["model_version_id"] == model_version_id
            assert payload["input_uri"] == _PROJECT_INPUT_URI
            assert payload["input_source_kind"] == "input_uri"
            assert payload["preview_image_uri"].endswith("preview.jpg")
            assert payload["result_object_key"].endswith("raw-result.json")
            assert payload["runtime_session_info"]["metadata"]["runtime_mode"] == "sync"
            _assert_task_native_payload(spec=spec, payload=payload)
    finally:
        session_factory.engine.dispose()


@pytest.mark.parametrize("spec", _TASK_SPECS, ids=lambda item: item.task_type)
def test_non_detection_async_inference_task_result_round_trip(
    tmp_path: Path,
    spec: _TaskTypeApiSpec,
) -> None:
    """验证非 detection inference task 可以完成 create -> process -> detail/result 闭环。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path, task_type=spec.task_type)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        spec=spec,
    )
    dataset_storage.write_bytes(_PROJECT_INPUT_URI, b"fake-image")

    try:
        with client:
            deployment_instance_id = _create_deployment_instance(
                client=client,
                spec=spec,
                model_version_id=model_version_id,
            )

            start_response = client.post(
                f"/api/v1/models/{spec.task_type}/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_model_headers(),
            )
            assert start_response.status_code == 200
            assert start_response.json()["process_state"] == "running"

            create_response = client.post(
                f"/api/v1/models/{spec.task_type}/inference-tasks",
                headers=_build_inference_headers(),
                json=_build_async_inference_task_payload(
                    spec=spec,
                    deployment_instance_id=deployment_instance_id,
                ),
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]
            assert submission["deployment_instance_id"] == deployment_instance_id
            assert submission["input_source_kind"] == "input_uri"

            pending_result_response = client.get(
                f"/api/v1/models/{spec.task_type}/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert pending_result_response.status_code == 200
            assert pending_result_response.json()["file_status"] == "pending"

            processed_result = _process_inference_task(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
                client=client,
                spec=spec,
                task_id=task_id,
            )
            assert processed_result.task_id == task_id
            assert processed_result.deployment_instance_id == deployment_instance_id
            assert processed_result.input_uri == _PROJECT_INPUT_URI

            detail_response = client.get(
                f"/api/v1/models/{spec.task_type}/inference-tasks/{task_id}",
                headers=_build_task_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["deployment_instance_id"] == deployment_instance_id
            assert detail_payload["instance_id"] == f"{deployment_instance_id}:instance-0"
            assert detail_payload["input_uri"] == _PROJECT_INPUT_URI
            assert detail_payload["input_source_kind"] == "input_uri"
            assert detail_payload["result_object_key"].endswith("raw-result.json")
            assert detail_payload["preview_image_object_key"].endswith("preview.jpg")
            expected_item_count = 2 if spec.task_type == "classification" else 1
            assert detail_payload["item_count"] == expected_item_count

            result_response = client.get(
                f"/api/v1/models/{spec.task_type}/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert result_response.status_code == 200
            result_payload = result_response.json()
            assert result_payload["file_status"] == "ready"
            assert result_payload["payload"]["deployment_instance_id"] == deployment_instance_id
            assert result_payload["payload"]["input_uri"] == _PROJECT_INPUT_URI
            assert result_payload["payload"]["runtime_session_info"]["metadata"]["runtime_mode"] == "async"
            _assert_task_native_payload(spec=spec, payload=result_payload["payload"])
    finally:
        session_factory.engine.dispose()


def _create_test_client(
    tmp_path: Path,
    *,
    task_type: str,
):
    """创建绑定非 detection fake deployment supervisor 的测试客户端。"""

    context = create_api_test_context(
        tmp_path,
        database_name=f"amvision-{task_type}-api.db",
        enable_local_buffer_broker=False,
    )
    _attach_fake_deployment_supervisors(
        dataset_storage=context.dataset_storage,
        client=context.client,
        task_type=task_type,
    )
    return context.client, context.session_factory, context.dataset_storage


def _attach_fake_deployment_supervisors(
    *,
    dataset_storage: LocalDatasetStorage,
    client,
    task_type: str,
) -> None:
    """把指定 task type 的 sync/async supervisor 替换为 fake 实现。"""

    service_event_bus = getattr(client.app.state, "service_event_bus", None)
    setattr(
        client.app.state,
        f"{task_type}_sync_deployment_process_supervisor",
        FakeDeploymentProcessSupervisor(
            runtime_mode="sync",
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            service_event_bus=service_event_bus,
        ),
    )
    setattr(
        client.app.state,
        f"{task_type}_async_deployment_process_supervisor",
        FakeDeploymentProcessSupervisor(
            runtime_mode="async",
            dataset_storage_root_dir=str(dataset_storage.root_dir),
            service_event_bus=service_event_bus,
            starting_process_id=2000,
        ),
    )


def _create_deployment_instance(
    *,
    client,
    spec: _TaskTypeApiSpec,
    model_version_id: str,
) -> str:
    """通过 API 创建指定 task type 的 DeploymentInstance。"""

    response = client.post(
        f"/api/v1/models/{spec.task_type}/deployment-instances",
        headers=_build_model_headers(),
        json={
            "project_id": "project-1",
            "model_type": spec.model_type,
            "model_version_id": model_version_id,
            "runtime_backend": "pytorch",
            "device_name": "cpu",
            "display_name": f"{spec.task_type} deployment",
        },
    )
    assert response.status_code == 201
    return response.json()["deployment_instance_id"]


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    spec: _TaskTypeApiSpec,
) -> str:
    """写入一个供非 detection deployment 使用的最小 ModelVersion。"""

    checkpoint_uri = (
        f"projects/project-1/models/{spec.model_type}/{spec.task_type}-source-1/"
        "artifacts/checkpoints/best-checkpoint.pt"
    )
    labels_uri = (
        f"projects/project-1/models/{spec.model_type}/{spec.task_type}-source-1/"
        "artifacts/labels.txt"
    )
    dataset_storage.write_bytes(checkpoint_uri, b"fake-checkpoint")
    dataset_storage.write_text(labels_uri, "bolt\nnut\n")

    model_service = spec.model_service_cls(session_factory=session_factory)
    return model_service.register_training_output(
        spec.output_registration_cls(
            project_id="project-1",
            training_task_id=f"training-{spec.task_type}-source-1",
            model_name=f"{spec.model_type}-{spec.task_type}",
            model_scale="nano",
            task_type=spec.task_type,
            dataset_version_id=f"dataset-version-{spec.task_type}-source-1",
            checkpoint_file_id=f"checkpoint-file-{spec.task_type}-source-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id=f"labels-file-{spec.task_type}-source-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt", "nut"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _build_model_headers() -> dict[str, str]:
    """构建 deployment API 所需请求头。"""

    return build_test_headers(scopes="models:read,models:write")


def _build_inference_headers() -> dict[str, str]:
    """构建 inference task create 接口请求头。"""

    return build_test_headers(scopes="models:read,tasks:write")


def _build_task_headers() -> dict[str, str]:
    """构建 inference task 查询接口请求头。"""

    return build_test_headers(scopes="tasks:read")


def _build_direct_infer_payload(spec: _TaskTypeApiSpec) -> dict[str, object]:
    """构建 sync /infer 请求体。"""

    payload: dict[str, object] = {
        "model_type": spec.model_type,
        "input_uri": _PROJECT_INPUT_URI,
        "save_result_image": True,
    }
    if spec.task_type == "classification":
        payload["top_k"] = 2
    elif spec.task_type == "segmentation":
        payload["score_threshold"] = 0.25
        payload["mask_threshold"] = 0.4
    elif spec.task_type == "pose":
        payload["score_threshold"] = 0.25
        payload["keypoint_confidence_threshold"] = 0.35
    elif spec.task_type == "obb":
        payload["score_threshold"] = 0.25
    return payload


def _build_async_inference_task_payload(
    *,
    spec: _TaskTypeApiSpec,
    deployment_instance_id: str,
) -> dict[str, object]:
    """构建 async inference task create 请求体。"""

    payload = {
        "project_id": "project-1",
        "deployment_instance_id": deployment_instance_id,
        "model_type": spec.model_type,
        "input_uri": _PROJECT_INPUT_URI,
        "save_result_image": True,
    }
    payload.update(
        {
            key: value
            for key, value in _build_direct_infer_payload(spec).items()
            if key not in {"input_uri", "model_type"}
        }
    )
    return payload


def _process_inference_task(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    client,
    spec: _TaskTypeApiSpec,
    task_id: str,
):
    """直接通过 service 执行一条 non-detection inference task。"""

    service = spec.inference_task_service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=getattr(client.app.state, "queue_backend", None),
        deployment_process_supervisor=getattr(
            client.app.state,
            f"{spec.task_type}_async_deployment_process_supervisor",
        ),
    )
    return service.process_inference_task(task_id)


def _assert_task_native_payload(
    *,
    spec: _TaskTypeApiSpec,
    payload: dict[str, object],
) -> None:
    """按 task type 断言结果载荷形状。"""

    assert payload["latency_ms"] == 9.7
    assert payload["image_width"] == 64
    assert payload["image_height"] == 64

    if spec.task_type == "classification":
        assert payload["category_count"] == 2
        assert payload["top_category"]["class_name"] == "bolt"
        assert payload["categories"][0]["class_name"] == "bolt"
        return

    assert payload["instance_count"] == 1
    assert payload["instances"][0]["class_name"] == "bolt"

    if spec.task_type == "segmentation":
        assert payload["instances"][0]["mask_area"] == 324.0
        assert len(payload["instances"][0]["segments"]) == 1
    elif spec.task_type == "pose":
        assert len(payload["instances"][0]["keypoints"]) == 2
        assert payload["instances"][0]["kpt_shape"] == [17, 3]
    elif spec.task_type == "obb":
        assert payload["instances"][0]["angle"] == 12.5
