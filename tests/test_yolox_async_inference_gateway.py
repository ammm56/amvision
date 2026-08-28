"""detection async inference gateway 队列路由测试。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.inference.detection_async_inference_gateway import (
    DetectionAsyncInferenceGatewayDispatcher,
    DetectionAsyncInferenceGatewayDispatcherRegistry,
    QueueBackedDetectionAsyncInferenceClient,
)
from backend.service.application.models.inference.inference_gateway import (
    build_async_inference_preview_object_key,
    serialize_async_inference_execution_result,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
    DetectionRuntimeSessionInfo,
    DetectionRuntimeTensorSpec,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessExecution,
)
from backend.service.application.runtime.deployment.runtime_factory import (
    _build_async_inference_gateway_execution_handler,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.queue.local_file import (
    LocalFileQueueBackend,
    LocalFileQueueSettings,
)


def test_async_gateway_dispatcher_consumes_owner_deployment_queue(
    tmp_path: Path,
) -> None:
    """验证 dispatcher 只通过 owner 与 deployment 专属 gateway 队列完成一次请求响应。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    process_config = _build_process_config(dataset_storage=dataset_storage)
    captured_deployment_ids: list[str] = []
    captured_input_uris: list[str] = []

    def _execute(**kwargs: object) -> dict[str, object]:
        """记录被 dispatcher 转发的请求并返回最小成功载荷。"""

        captured_process_config = kwargs["process_config"]
        assert isinstance(captured_process_config, DeploymentProcessConfig)
        captured_deployment_ids.append(captured_process_config.deployment_instance_id)
        captured_request = kwargs["request"]
        assert captured_request.input_image_bytes is None
        assert isinstance(captured_request.input_uri, str)
        assert (
            dataset_storage.resolve(captured_request.input_uri).read_bytes()
            == b"fake-image"
        )
        captured_input_uris.append(captured_request.input_uri)
        return _build_gateway_result(instance_id="deployment-instance-1:instance-0")

    dispatcher = DetectionAsyncInferenceGatewayDispatcher(
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
        client = QueueBackedDetectionAsyncInferenceClient(
            queue_backend=queue_backend,
            request_timeout_seconds=2.0,
            response_poll_interval_seconds=0.01,
            client_id="worker-1",
            dataset_storage=dataset_storage,
        )
        result = client.execute_inference(
            process_config=process_config,
            request=DetectionPredictionRequest(
                input_image_bytes=b"fake-image",
                score_threshold=0.3,
                save_result_image=True,
            ),
            owner_id="backend-service-owner-1",
        )
    finally:
        dispatcher.stop()

    assert captured_deployment_ids == ["deployment-instance-1"]
    assert len(captured_input_uris) == 1
    assert not dataset_storage.resolve(captured_input_uris[0]).exists()
    assert result["instance_id"] == "deployment-instance-1:instance-0"
    assert not (tmp_path / "queue" / "detection-async-inference-gateway").exists()
    assert not list((tmp_path / "queue").glob("detection-ai-rsp-*"))
    assert (
        dispatcher.request_queue_name == "inference-gateway-backend-service-owner-1-1"
    )


def test_async_gateway_assigns_request_scoped_object_store_output(
    tmp_path: Path,
) -> None:
    """验证 gateway 把结果 key 下沉给 deployment worker，不在父进程搬运图片。"""

    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    process_config = _build_process_config(dataset_storage=dataset_storage)
    execution_result = DetectionPredictionExecutionResult(
        detections=(),
        latency_ms=1.0,
        image_width=2,
        image_height=2,
        preview_image_bytes=None,
        runtime_session_info=DetectionRuntimeSessionInfo(
            backend_name="onnxruntime",
            model_uri="models/model.onnx",
            device_name="cpu",
            input_spec=DetectionRuntimeTensorSpec(
                name="images", shape=(1, 3, 2, 2), dtype="float32"
            ),
            output_spec=DetectionRuntimeTensorSpec(
                name="detections", shape=(-1, 7), dtype="float32"
            ),
        ),
    )

    class _Supervisor:
        """记录 gateway 指定输出 key 的测试 supervisor。"""

        def run_inference(self, **kwargs: object) -> DeploymentProcessExecution:
            """模拟 worker 已直接写入 ObjectStore。"""

            object_key = str(kwargs["preview_output_object_key"])
            dataset_storage.write_bytes(object_key, b"preview")
            return DeploymentProcessExecution(
                deployment_instance_id=process_config.deployment_instance_id,
                instance_id="deployment-instance-1:instance-0",
                execution_result=execution_result,
                preview_image_transfer={
                    "object_key": object_key,
                    "size": len(b"preview"),
                    "media_type": "image/jpeg",
                },
            )

    handler = _build_async_inference_gateway_execution_handler(
        deployment_process_supervisor=_Supervisor(),  # type: ignore[arg-type]
        async_inference_service_id="backend-service-owner-1",
    )
    request = DetectionPredictionRequest(
        input_uri="runtime/transfers/request/input.bin",
        score_threshold=0.3,
        save_result_image=True,
    )
    result = handler(
        request_id="async-inference-request-1",
        process_config=process_config,
        request=request,
    )

    expected_key = build_async_inference_preview_object_key(
        owner_id="backend-service-owner-1",
        deployment_instance_id=process_config.deployment_instance_id,
        request_id="async-inference-request-1",
    )
    assert result["preview_image_object_key"] == expected_key
    assert dataset_storage.resolve(expected_key).read_bytes() == b"preview"
    assert "preview_image_bytes" not in result["execution_result"]


def test_async_gateway_client_requires_owner_id(tmp_path: Path) -> None:
    """验证 async gateway client 不允许写入无 owner 的全局请求队列。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    process_config = _build_process_config(dataset_storage=dataset_storage)
    client = QueueBackedDetectionAsyncInferenceClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        request_timeout_seconds=0.1,
        response_poll_interval_seconds=0.01,
        client_id="worker-1",
    )

    with pytest.raises(InvalidRequestError, match="owner_id"):
        client.execute_inference(
            process_config=process_config,
            request=DetectionPredictionRequest(
                input_image_bytes=b"fake-image",
                score_threshold=0.3,
                save_result_image=True,
            ),
            owner_id="",
        )

    assert not (tmp_path / "queue" / "detection-async-inference-gateway").exists()
    assert not list((tmp_path / "queue").glob("detection-ai-rsp-*"))


def test_async_gateway_persists_only_preview_reference_in_response_queue(
    tmp_path: Path,
) -> None:
    """验证异步响应队列不含图片 bytes，client 从临时 ObjectStore 引用读取。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    process_config = _build_process_config(dataset_storage=dataset_storage)
    queued_results: list[dict[str, object]] = []

    def _execute(**kwargs: object) -> dict[str, object]:
        request_id = str(kwargs["request_id"])
        preview_object_key = build_async_inference_preview_object_key(
            owner_id="backend-service-owner-1",
            deployment_instance_id="deployment-instance-1",
            request_id=request_id,
        )
        dataset_storage.write_bytes(preview_object_key, b"preview-image")
        payload = serialize_async_inference_execution_result(
            task_type="detection",
            result=SimpleNamespace(
                instance_id="deployment-instance-1:instance-0",
                execution_result=DetectionPredictionExecutionResult(
                    detections=(),
                    latency_ms=1.0,
                    image_width=2,
                    image_height=2,
                    preview_image_bytes=b"preview-image",
                    runtime_session_info=DetectionRuntimeSessionInfo(
                        backend_name="onnxruntime",
                        model_uri="models/model.onnx",
                        device_name="cpu",
                        input_spec=DetectionRuntimeTensorSpec(
                            name="images", shape=(1, 3, 2, 2), dtype="float32"
                        ),
                        output_spec=DetectionRuntimeTensorSpec(
                            name="detections", shape=(-1, 7), dtype="float32"
                        ),
                    ),
                ),
            ),
            preview_image_object_key=preview_object_key,
        )
        queued_results.append(payload)
        return payload

    dispatcher = DetectionAsyncInferenceGatewayDispatcher(
        queue_backend=queue_backend,
        execution_handler=_execute,
        service_id="backend-service-owner-1",
        deployment_instance_id="deployment-instance-1",
        poll_interval_seconds=0.01,
    )
    dispatcher.dataset_storage = dataset_storage
    client = QueueBackedDetectionAsyncInferenceClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        request_timeout_seconds=2.0,
        response_poll_interval_seconds=0.01,
        client_id="worker-1",
    )
    dispatcher.start()
    try:
        result = client.execute_inference(
            process_config=process_config,
            request=DetectionPredictionRequest(
                input_uri="models/labels.txt",
                score_threshold=0.3,
                save_result_image=True,
            ),
            owner_id="backend-service-owner-1",
        )
    finally:
        dispatcher.stop()

    assert len(queued_results) == 1
    queued_execution = queued_results[0]["execution_result"]
    assert isinstance(queued_execution, dict)
    assert "preview_image_bytes" not in queued_execution
    assert "preview_image_bytes_base64" not in queued_execution
    result_execution = result["execution_result"]
    assert isinstance(result_execution, dict)
    assert result_execution["preview_image_bytes"] == b"preview-image"
    transfer_root = dataset_storage.resolve("runtime/transfers/async-inference")
    assert not list(transfer_root.rglob("preview.bin"))


def test_async_gateway_routes_multiple_service_ids_independently(
    tmp_path: Path,
) -> None:
    """验证多个 async inference service 通过各自 owner+deployment 队列独立消费。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    process_config = _build_process_config(dataset_storage=dataset_storage)
    captured_service_ids: list[str] = []

    def _build_execute(service_id: str) -> Callable[..., dict[str, object]]:
        """构造带 service id 标记的最小 gateway 执行函数。"""

        def _execute(**kwargs: object) -> dict[str, object]:
            captured_process_config = kwargs["process_config"]
            assert isinstance(captured_process_config, DeploymentProcessConfig)
            captured_service_ids.append(service_id)
            return _build_gateway_result(
                instance_id=f"{service_id}:deployment-instance-1:instance-0"
            )

        return _execute

    dispatcher_a = DetectionAsyncInferenceGatewayDispatcher(
        queue_backend=queue_backend,
        execution_handler=_build_execute("backend-service-a"),
        service_id="backend-service-a",
        deployment_instance_id="deployment-instance-1",
        poll_interval_seconds=0.01,
        response_queue_cleanup_interval_seconds=1000.0,
    )
    dispatcher_b = DetectionAsyncInferenceGatewayDispatcher(
        queue_backend=queue_backend,
        execution_handler=_build_execute("backend-service-b"),
        service_id="backend-service-b",
        deployment_instance_id="deployment-instance-1",
        poll_interval_seconds=0.01,
        response_queue_cleanup_interval_seconds=1000.0,
    )
    dispatcher_a.dataset_storage = dataset_storage
    dispatcher_b.dataset_storage = dataset_storage
    client = QueueBackedDetectionAsyncInferenceClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        request_timeout_seconds=2.0,
        response_poll_interval_seconds=0.01,
        client_id="worker-1",
    )
    dispatcher_a.start()
    dispatcher_b.start()
    try:
        result_a = client.execute_inference(
            process_config=process_config,
            request=DetectionPredictionRequest(
                input_image_bytes=b"a",
                score_threshold=0.3,
                save_result_image=False,
            ),
            owner_id="backend-service-a",
        )
        result_b = client.execute_inference(
            process_config=process_config,
            request=DetectionPredictionRequest(
                input_image_bytes=b"b",
                score_threshold=0.3,
                save_result_image=False,
            ),
            owner_id="backend-service-b",
        )
    finally:
        dispatcher_a.stop()
        dispatcher_b.stop()

    assert (
        result_a["instance_id"] == "backend-service-a:deployment-instance-1:instance-0"
    )
    assert (
        result_b["instance_id"] == "backend-service-b:deployment-instance-1:instance-0"
    )
    assert captured_service_ids == ["backend-service-a", "backend-service-b"]
    assert not list((tmp_path / "queue").glob("detection-ai-rsp-*"))


def test_async_gateway_registry_routes_multiple_deployments_independently(
    tmp_path: Path,
) -> None:
    """验证同一 service 内多个 async deployment 拥有独立 gateway 队列和 dispatcher。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "files"))
    )
    captured_deployment_ids: list[str] = []

    def _execute(**kwargs: object) -> dict[str, object]:
        """记录 registry dispatcher 转发的 deployment id 并返回最小成功载荷。"""

        captured_process_config = kwargs["process_config"]
        assert isinstance(captured_process_config, DeploymentProcessConfig)
        deployment_instance_id = captured_process_config.deployment_instance_id
        captured_deployment_ids.append(deployment_instance_id)
        return _build_gateway_result(instance_id=f"{deployment_instance_id}:instance-0")

    registry = DetectionAsyncInferenceGatewayDispatcherRegistry(
        queue_backend=queue_backend,
        execution_handler=_execute,
        service_id="backend-service-main",
        dataset_storage=dataset_storage,
        poll_interval_seconds=0.01,
        response_queue_cleanup_interval_seconds=1000.0,
    )
    registry.start()
    try:
        dispatcher_1 = registry.ensure_dispatcher_for_deployment(
            "deployment-instance-1"
        )
        dispatcher_2 = registry.ensure_dispatcher_for_deployment(
            "deployment-instance-2"
        )
        client = QueueBackedDetectionAsyncInferenceClient(
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
            request_timeout_seconds=2.0,
            response_poll_interval_seconds=0.01,
            client_id="worker-1",
        )
        result_1 = client.execute_inference(
            process_config=_build_process_config(
                dataset_storage=dataset_storage,
                deployment_instance_id="deployment-instance-1",
            ),
            request=DetectionPredictionRequest(
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
            request=DetectionPredictionRequest(
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
    assert dispatcher_1.request_queue_name == "inference-gateway-backend-service-main-1"
    assert dispatcher_2.request_queue_name == "inference-gateway-backend-service-main-2"
    assert result_1["instance_id"] == "deployment-instance-1:instance-0"
    assert result_2["instance_id"] == "deployment-instance-2:instance-0"
    assert captured_deployment_ids == ["deployment-instance-1", "deployment-instance-2"]
    assert not list((tmp_path / "queue").glob("detection-ai-rsp-*"))


def _build_process_config(
    *,
    dataset_storage: LocalDatasetStorage,
    deployment_instance_id: str = "deployment-instance-1",
) -> DeploymentProcessConfig:
    """构造可被 gateway 反序列化的最小 process config。"""

    runtime_artifact_storage_uri = "models/model.onnx"
    labels_storage_uri = "models/labels.txt"
    dataset_storage.write_bytes(runtime_artifact_storage_uri, b"fake-model")
    dataset_storage.write_bytes(labels_storage_uri, b"barcode\n")
    return DeploymentProcessConfig(
        deployment_instance_id=deployment_instance_id,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
        runtime_target=RuntimeTargetSnapshot(
            project_id="project-1",
            model_id="model-1",
            model_version_id="model-version-1",
            model_build_id="model-build-1",
            model_name="yolox-test",
            model_scale="nano",
            model_type="yolox",
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


def _build_gateway_result(*, instance_id: str) -> dict[str, object]:
    """按当前 gateway 结构化响应合同生成最小 detection 结果。"""

    return serialize_async_inference_execution_result(
        task_type="detection",
        result=SimpleNamespace(
            instance_id=instance_id,
            execution_result=DetectionPredictionExecutionResult(
                detections=(),
                latency_ms=1.0,
                image_width=2,
                image_height=2,
                preview_image_bytes=None,
                runtime_session_info=DetectionRuntimeSessionInfo(
                    backend_name="onnxruntime",
                    model_uri="models/model.onnx",
                    device_name="cpu",
                    input_spec=DetectionRuntimeTensorSpec(
                        name="images",
                        shape=(1, 3, 2, 2),
                        dtype="float32",
                    ),
                    output_spec=DetectionRuntimeTensorSpec(
                        name="detections",
                        shape=(-1, 7),
                        dtype="float32",
                    ),
                ),
            ),
        ),
    )
