"""YOLOX async inference gateway 队列路由测试。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_async_inference_gateway import (
    QueueBackedYoloXAsyncInferenceClient,
    YoloXAsyncInferenceGatewayDispatcher,
    YoloXAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
)
from backend.service.application.runtime.yolox_predictor import YoloXPredictionRequest
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_async_gateway_dispatcher_consumes_owner_deployment_queue(tmp_path: Path) -> None:
    """验证 dispatcher 只通过 owner 与 deployment 专属 gateway 队列完成一次请求响应。"""

    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue")))
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    process_config = _build_process_config(dataset_storage=dataset_storage)
    captured_deployment_ids: list[str] = []

    def _execute(**kwargs: object) -> dict[str, object]:
        """记录被 dispatcher 转发的请求并返回最小成功载荷。"""

        captured_process_config = kwargs["process_config"]
        assert isinstance(captured_process_config, YoloXDeploymentProcessConfig)
        captured_deployment_ids.append(captured_process_config.deployment_instance_id)
        return {
            "instance_id": "deployment-instance-1:instance-0",
            "detections": [],
            "latency_ms": 1.0,
            "image_width": 2,
            "image_height": 2,
            "preview_image_bytes_base64": None,
            "runtime_session_info": {"runtime_backend": "onnxruntime"},
        }

    dispatcher = YoloXAsyncInferenceGatewayDispatcher(
        queue_backend=queue_backend,
        execution_handler=_execute,
        service_id="backend-service-owner-1",
        deployment_instance_id="deployment-instance-1",
        poll_interval_seconds=0.01,
        response_queue_cleanup_interval_seconds=1000.0,
    )
    dispatcher.dataset_storage = dataset_storage
    dispatcher.start()
    try:
        client = QueueBackedYoloXAsyncInferenceClient(
            queue_backend=queue_backend,
            request_timeout_seconds=2.0,
            response_poll_interval_seconds=0.01,
            client_id="worker-1",
        )
        result = client.execute_inference(
            process_config=process_config,
            request=YoloXPredictionRequest(
                input_image_bytes=b"fake-image",
                score_threshold=0.3,
                save_result_image=True,
            ),
            owner_id="backend-service-owner-1",
        )
    finally:
        dispatcher.stop()

    assert captured_deployment_ids == ["deployment-instance-1"]
    assert result["instance_id"] == "deployment-instance-1:instance-0"
    assert not (tmp_path / "queue" / "yolox-async-inference-gateway").exists()
    assert not list((tmp_path / "queue").glob("yolox-ai-rsp-*"))
    assert dispatcher.request_queue_name == "yolox-ai-gw-backend-service-owner-1-1"


def test_async_gateway_client_requires_owner_id(tmp_path: Path) -> None:
    """验证 async gateway client 不允许写入无 owner 的全局请求队列。"""

    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue")))
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    process_config = _build_process_config(dataset_storage=dataset_storage)
    client = QueueBackedYoloXAsyncInferenceClient(
        queue_backend=queue_backend,
        request_timeout_seconds=0.1,
        response_poll_interval_seconds=0.01,
        client_id="worker-1",
    )

    with pytest.raises(InvalidRequestError, match="owner_id"):
        client.execute_inference(
            process_config=process_config,
            request=YoloXPredictionRequest(
                input_image_bytes=b"fake-image",
                score_threshold=0.3,
                save_result_image=True,
            ),
            owner_id="",
        )

    assert not (tmp_path / "queue" / "yolox-async-inference-gateway").exists()
    assert not list((tmp_path / "queue").glob("yolox-ai-rsp-*"))


def test_async_gateway_routes_multiple_service_ids_independently(tmp_path: Path) -> None:
    """验证多个 async inference service 通过各自 owner+deployment 队列独立消费。"""

    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue")))
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    process_config = _build_process_config(dataset_storage=dataset_storage)
    captured_service_ids: list[str] = []

    def _build_execute(service_id: str) -> Callable[..., dict[str, object]]:
        """构造带 service id 标记的最小 gateway 执行函数。"""

        def _execute(**kwargs: object) -> dict[str, object]:
            captured_process_config = kwargs["process_config"]
            assert isinstance(captured_process_config, YoloXDeploymentProcessConfig)
            captured_service_ids.append(service_id)
            return {
                "instance_id": f"{service_id}:deployment-instance-1:instance-0",
                "detections": [],
                "latency_ms": 1.0,
                "image_width": 2,
                "image_height": 2,
                "preview_image_bytes_base64": None,
                "runtime_session_info": {"runtime_backend": "onnxruntime"},
            }

        return _execute

    dispatcher_a = YoloXAsyncInferenceGatewayDispatcher(
        queue_backend=queue_backend,
        execution_handler=_build_execute("backend-service-a"),
        service_id="backend-service-a",
        deployment_instance_id="deployment-instance-1",
        poll_interval_seconds=0.01,
        response_queue_cleanup_interval_seconds=1000.0,
    )
    dispatcher_b = YoloXAsyncInferenceGatewayDispatcher(
        queue_backend=queue_backend,
        execution_handler=_build_execute("backend-service-b"),
        service_id="backend-service-b",
        deployment_instance_id="deployment-instance-1",
        poll_interval_seconds=0.01,
        response_queue_cleanup_interval_seconds=1000.0,
    )
    dispatcher_a.dataset_storage = dataset_storage
    dispatcher_b.dataset_storage = dataset_storage
    client = QueueBackedYoloXAsyncInferenceClient(
        queue_backend=queue_backend,
        request_timeout_seconds=2.0,
        response_poll_interval_seconds=0.01,
        client_id="worker-1",
    )
    dispatcher_a.start()
    dispatcher_b.start()
    try:
        result_a = client.execute_inference(
            process_config=process_config,
            request=YoloXPredictionRequest(
                input_image_bytes=b"a",
                score_threshold=0.3,
                save_result_image=False,
            ),
            owner_id="backend-service-a",
        )
        result_b = client.execute_inference(
            process_config=process_config,
            request=YoloXPredictionRequest(
                input_image_bytes=b"b",
                score_threshold=0.3,
                save_result_image=False,
            ),
            owner_id="backend-service-b",
        )
    finally:
        dispatcher_a.stop()
        dispatcher_b.stop()

    assert result_a["instance_id"] == "backend-service-a:deployment-instance-1:instance-0"
    assert result_b["instance_id"] == "backend-service-b:deployment-instance-1:instance-0"
    assert captured_service_ids == ["backend-service-a", "backend-service-b"]
    assert not list((tmp_path / "queue").glob("yolox-ai-rsp-*"))


def test_async_gateway_registry_routes_multiple_deployments_independently(tmp_path: Path) -> None:
    """验证同一 service 内多个 async deployment 拥有独立 gateway 队列和 dispatcher。"""

    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue")))
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))
    captured_deployment_ids: list[str] = []

    def _execute(**kwargs: object) -> dict[str, object]:
        """记录 registry dispatcher 转发的 deployment id 并返回最小成功载荷。"""

        captured_process_config = kwargs["process_config"]
        assert isinstance(captured_process_config, YoloXDeploymentProcessConfig)
        deployment_instance_id = captured_process_config.deployment_instance_id
        captured_deployment_ids.append(deployment_instance_id)
        return {
            "instance_id": f"{deployment_instance_id}:instance-0",
            "detections": [],
            "latency_ms": 1.0,
            "image_width": 2,
            "image_height": 2,
            "preview_image_bytes_base64": None,
            "runtime_session_info": {"runtime_backend": "onnxruntime"},
        }

    registry = YoloXAsyncInferenceGatewayDispatcherRegistry(
        queue_backend=queue_backend,
        execution_handler=_execute,
        service_id="backend-service-main",
        dataset_storage=dataset_storage,
        poll_interval_seconds=0.01,
        response_queue_cleanup_interval_seconds=1000.0,
    )
    registry.start()
    try:
        dispatcher_1 = registry.ensure_dispatcher_for_deployment("deployment-instance-1")
        dispatcher_2 = registry.ensure_dispatcher_for_deployment("deployment-instance-2")
        client = QueueBackedYoloXAsyncInferenceClient(
            queue_backend=queue_backend,
            request_timeout_seconds=2.0,
            response_poll_interval_seconds=0.01,
            client_id="worker-1",
        )
        result_1 = client.execute_inference(
            process_config=_build_process_config(
                dataset_storage=dataset_storage,
                deployment_instance_id="deployment-instance-1",
            ),
            request=YoloXPredictionRequest(
                input_image_bytes=b"a",
                score_threshold=0.3,
                save_result_image=False,
            ),
            owner_id="backend-service-main",
        )
        result_2 = client.execute_inference(
            process_config=_build_process_config(
                dataset_storage=dataset_storage,
                deployment_instance_id="deployment-instance-2",
            ),
            request=YoloXPredictionRequest(
                input_image_bytes=b"b",
                score_threshold=0.3,
                save_result_image=False,
            ),
            owner_id="backend-service-main",
        )
    finally:
        registry.stop()

    assert dispatcher_1.request_queue_name != dispatcher_2.request_queue_name
    assert (tmp_path / "queue" / dispatcher_1.request_queue_name).is_dir()
    assert (tmp_path / "queue" / dispatcher_2.request_queue_name).is_dir()
    assert dispatcher_1.request_queue_name == "yolox-ai-gw-backend-service-main-1"
    assert dispatcher_2.request_queue_name == "yolox-ai-gw-backend-service-main-2"
    assert result_1["instance_id"] == "deployment-instance-1:instance-0"
    assert result_2["instance_id"] == "deployment-instance-2:instance-0"
    assert captured_deployment_ids == ["deployment-instance-1", "deployment-instance-2"]
    assert not list((tmp_path / "queue").glob("yolox-ai-rsp-*"))


def _build_process_config(
    *,
    dataset_storage: LocalDatasetStorage,
    deployment_instance_id: str = "deployment-instance-1",
) -> YoloXDeploymentProcessConfig:
    """构造可被 gateway 反序列化的最小 process config。"""

    runtime_artifact_storage_uri = "models/model.onnx"
    labels_storage_uri = "models/labels.txt"
    dataset_storage.write_bytes(runtime_artifact_storage_uri, b"fake-model")
    dataset_storage.write_bytes(labels_storage_uri, b"barcode\n")
    return YoloXDeploymentProcessConfig(
        deployment_instance_id=deployment_instance_id,
        project_id="project-1",
        instance_count=1,
        runtime_target=RuntimeTargetSnapshot(
            project_id="project-1",
            model_id="model-1",
            model_version_id="model-version-1",
            model_build_id="model-build-1",
            model_name="yolox-test",
            model_scale="nano",
            task_type="detection",
            source_kind="training-output",
            runtime_profile_id=None,
            runtime_backend="onnxruntime",
            device_name="cpu",
            runtime_precision="fp32",
            input_size=(64, 64),
            labels=("barcode",),
            runtime_artifact_file_id="model-file-1",
            runtime_artifact_storage_uri=runtime_artifact_storage_uri,
            runtime_artifact_path=dataset_storage.resolve(runtime_artifact_storage_uri),
            runtime_artifact_file_type="yolox-onnx-model",
            checkpoint_file_id=None,
            checkpoint_storage_uri=None,
            checkpoint_path=None,
            labels_storage_uri=labels_storage_uri,
        ),
    )