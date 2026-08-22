"""独立 inference daemon 本地控制通道测试。"""

from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore, Event, Thread
from time import monotonic_ns, perf_counter, sleep

import pytest

from backend.contracts.buffers import BufferRef
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.local_buffers import (
    DirectMmapLocalBufferReader,
    DirectMmapLocalBufferWriter,
    LocalBufferBrokerPoolSettings,
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)
from backend.service.application.models.inference.inference_gateway import (
    _serialize_process_config,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionRequest,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionInstance,
    SegmentationPredictionRequest,
    SegmentationRuntimeSessionInfo,
    SegmentationRuntimeTensorSpec,
)
from backend.service.application.runtime.deployment import (
    inference_local_mmap as inference_local_mmap_module,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessExecution,
    DeploymentProcessHealth,
    DeploymentProcessStatus,
)
from backend.service.application.runtime.deployment.inference_control import (
    INFERENCE_CONTROL_RESPONSE_QUEUE_PREFIX,
    InferenceControlBinding,
    InferenceControlDispatcher,
    QueueBackedInferenceControlClient,
)
from backend.service.application.runtime.deployment.inference_local_mmap import (
    InferenceLocalMmapClient,
    InferenceLocalMmapServer,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
)
from backend.service.infrastructure.queue.local_file import (
    LocalFileQueueBackend,
    LocalFileQueueSettings,
)
from tests.runtime_pool_test_support import (
    build_test_execution_result,
    build_test_runtime_target,
    create_test_dataset_storage,
)


class _FakeSupervisor:
    """记录控制动作并返回固定状态的 daemon 侧 supervisor。"""

    def __init__(self, *, dataset_storage) -> None:
        self.dataset_storage = dataset_storage
        self.actions: list[str] = []

    def start_deployment(self, config):
        self.actions.append("start")
        return _status(config, desired_state="running", process_state="running")

    def stop_deployment(self, config):
        self.actions.append("stop")
        return _status(config, desired_state="stopped", process_state="stopped")

    def get_status(self, config):
        self.actions.append("status")
        return _status(config, desired_state="running", process_state="running")

    def warmup_deployment(self, config):
        self.actions.append("warmup")
        return _health(config)

    def get_health(self, config):
        self.actions.append("health")
        return _health(config)

    def reset_deployment(self, config):
        self.actions.append("reset")
        return _health(config)

    def run_inference(self, *, config, request, preview_output_lease=None):
        del preview_output_lease
        self.actions.append("infer")
        assert request.input_image_bytes is None
        assert request.input_uri is not None
        assert self.dataset_storage.resolve(request.input_uri).is_file()
        return DeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-1",
            execution_result=build_test_execution_result(
                runtime_target=config.runtime_target
            ),
        )


class _FakeRegistry:
    """记录 async dispatcher 生命周期。"""

    def __init__(self) -> None:
        self.started: list[str] = []

    def ensure_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        self.started.append(deployment_instance_id)

    def stop_dispatcher_for_deployment(self, deployment_instance_id: str) -> None:
        if deployment_instance_id in self.started:
            self.started.remove(deployment_instance_id)


class _TimeoutMmapClient:
    """模拟请求发布后传输状态不确定的 mmap client。"""

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        del payload
        raise OperationTimeoutError("等待 inference mmap 响应超时")


class _FakeRefSupervisor(_FakeSupervisor):
    """验证 mmap 热路径保持 BufferRef，不读取或物化图片。"""

    def run_inference(self, *, config, request, preview_output_lease=None):
        """记录 infer 并校验 task-native request 仍携带 BufferRef。"""

        del preview_output_lease
        self.actions.append("infer")
        assert request.input_image_bytes is None
        assert request.input_uri is None
        assert request.input_image_payload is not None
        assert request.input_image_payload["transport_kind"] == "buffer"
        assert request.input_image_payload["buffer_ref"]["size"] == 12
        return DeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-mmap",
            execution_result=build_test_execution_result(
                runtime_target=config.runtime_target
            ),
        )


class _FakePreviewSupervisor(_FakeRefSupervisor):
    """模拟 worker 直接写 LocalBuffer，响应只返回传输元数据。"""

    def __init__(self, *, dataset_storage, preview_buffer_writer) -> None:
        super().__init__(dataset_storage=dataset_storage)
        self.preview_buffer_writer = preview_buffer_writer

    def run_inference(self, *, config, request, preview_output_lease=None):
        execution = super().run_inference(
            config=config,
            request=request,
        )
        if not request.save_result_image:
            return execution
        assert preview_output_lease is not None
        self.preview_buffer_writer.write_lease_bytes(
            lease=preview_output_lease,
            content=_one_pixel_png(),
        )
        return replace(
            execution,
            preview_image_transfer={
                "size": len(_one_pixel_png()),
                "media_type": "image/png",
            },
        )


class _SlowMutationSupervisor(_FakeSupervisor):
    """模拟 runtime session 释放时间超过只读控制超时的 supervisor。"""

    def stop_deployment(self, config):
        sleep(0.15)
        return super().stop_deployment(config)

    def reset_deployment(self, config):
        sleep(0.15)
        return super().reset_deployment(config)


class _FakeSegmentationSupervisor(_FakeSupervisor):
    """返回带实例轮廓的 segmentation 结果，验证其走 mmap 页池。"""

    def run_inference(self, *, config, request, preview_output_lease=None):
        del preview_output_lease
        self.actions.append("infer")
        assert request.input_image_bytes is None
        assert request.input_uri is None
        assert request.input_image_payload is not None
        assert request.input_image_payload["transport_kind"] == "buffer"
        return DeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-segmentation",
            execution_result=SegmentationPredictionExecutionResult(
                instances=(
                    SegmentationPredictionInstance(
                        bbox_xyxy=(1.0, 1.0, 3.0, 3.0),
                        score=0.9,
                        class_id=0,
                        class_name="bolt",
                        segments=(((1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)),),
                        mask_area=4.0,
                    ),
                ),
                latency_ms=2.0,
                image_width=4,
                image_height=4,
                preview_image_bytes=None,
                runtime_session_info=SegmentationRuntimeSessionInfo(
                    backend_name=config.runtime_target.runtime_backend,
                    model_uri=config.runtime_target.runtime_artifact_storage_uri,
                    device_name=config.runtime_target.device_name,
                    input_spec=SegmentationRuntimeTensorSpec(
                        name="images", shape=(1, 3, 4, 4), dtype="float32"
                    ),
                    output_specs=(
                        SegmentationRuntimeTensorSpec(
                            name="masks", shape=(1, 4, 4), dtype="float32"
                        ),
                    ),
                ),
            ),
        )


def _run_mmap_echo_server(*, path: str, ready_queue, stop_event) -> None:
    """在独立 spawn 进程中运行最小 mmap echo server。"""

    server = InferenceLocalMmapServer(
        path=path,
        request_handler=lambda payload: {"value": payload.get("value")},
        slot_count=96,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=16,
        poll_interval_seconds=0.0005,
    )
    server.start()
    ready_queue.put({"ready": True})
    try:
        stop_event.wait(timeout=60.0)
    finally:
        server.stop()


def _run_crashing_page_server(*, path: str, ready_event, page_written_event) -> None:
    """写完首个 overflow page 后立即退出，模拟 daemon 写入中崩溃。"""

    large_value = os.urandom(48 * 1024).hex()
    server = InferenceLocalMmapServer(
        path=path,
        request_handler=lambda _payload: {"value": large_value},
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=4,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=4,
        compression_threshold_bytes=1024 * 1024,
        poll_interval_seconds=0.0005,
    )

    def write_first_page_then_exit(**kwargs) -> None:
        page_indexes = kwargs["page_indexes"]
        content = kwargs["content"]
        view = server._mmap
        assert isinstance(page_indexes, list) and len(page_indexes) >= 2
        assert isinstance(content, bytes)
        assert view is not None
        page_index = page_indexes[0]
        page_offset = server._page_offset(page_index)
        body_offset = page_offset + inference_local_mmap_module._PAGE_HEADER.size
        chunk = content[: server.overflow_page_capacity_bytes]
        view[body_offset : body_offset + len(chunk)] = chunk
        inference_local_mmap_module._PAGE_HEADER.pack_into(
            view,
            page_offset,
            inference_local_mmap_module._PAGE_READY,
            page_indexes[1],
            len(chunk),
            inference_local_mmap_module.zlib.crc32(chunk),
            kwargs["slot_index"],
            kwargs["generation"],
            kwargs["owner_token"],
        )
        page_written_event.set()
        os._exit(91)

    server._write_pages = write_first_page_then_exit  # type: ignore[method-assign]
    server.start()
    ready_event.set()
    Event().wait(60.0)


def _run_busy_mmap_client(
    *,
    path: str,
    worker_index: int,
    request_count: int,
    start_event,
    result_queue,
) -> None:
    """在独立进程中连续提交会混合成功和满载响应的 mmap 请求。"""

    client = InferenceLocalMmapClient(
        path=path,
        request_timeout_seconds=5.0,
        poll_interval_seconds=0.0005,
    )
    success_count = 0
    busy_count = 0
    errors: list[str] = []
    try:
        start_event.wait(timeout=30.0)
        for request_index in range(request_count):
            try:
                response = client.request({"value": f"{worker_index}-{request_index}"})
                if response.get("ok") is True:
                    success_count += 1
                elif "满载" in str(response):
                    busy_count += 1
                else:
                    errors.append(f"unexpected response: {response}")
            except Exception as error:  # noqa: BLE001 - 子进程需要回传完整错误
                errors.append(f"{error.__class__.__name__}: {error}")
    finally:
        client.close()
    result_queue.put(
        {
            "worker_index": worker_index,
            "success_count": success_count,
            "busy_count": busy_count,
            "errors": errors,
        }
    )


def test_queue_backed_inference_control_round_trip(
    tmp_path: Path,
) -> None:
    """验证 mmap 承载只读状态，持久化队列只承载 deployment 变更。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-1",
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    fake_supervisor = _FakeSupervisor(dataset_storage=dataset_storage)
    fake_registry = _FakeRegistry()
    dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id="test-daemon",
        bindings_by_task_type={
            "detection": InferenceControlBinding(
                sync_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_gateway_registry=fake_registry,
            )
        },
        poll_interval_seconds=0.01,
    )
    mmap_path = tmp_path / "control-round-trip" / "inference.mmap"
    mmap_server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=dispatcher.handle_local_mmap_request,
        slot_count=4,
        slot_payload_capacity_bytes=64 * 1024,
    )
    mmap_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        local_mmap_client=mmap_client,
    )

    dispatcher.start()
    mmap_server.start()
    try:
        ping = client.ping()
        assert ping["ready"] is True
        assert ping["service_id"] == "test-daemon"
        assert ping["mailbox"]["protocol_version"] == 1
        assert client.start_deployment(config).process_state == "running"
        assert client.get_status(config).process_state == "running"
        assert client.get_health(config).process_state == "running"
        assert client.stop_deployment(config).process_state == "stopped"
    finally:
        mmap_client.close()
        mmap_server.stop()
        dispatcher.stop()

    assert fake_supervisor.actions == ["start", "status", "health", "stop"]


def test_preview_image_request_uses_mmap_v1(
    tmp_path: Path,
) -> None:
    """验证要求结果图的推理仍使用 mmap，而不是控制队列。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-preview",
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    buffer_settings = LocalBufferBrokerSettings(
        enabled=True,
        root_dir=str(tmp_path / "preview-buffers"),
        default_pool_name="image-test",
        pools=(
            LocalBufferBrokerPoolSettings(
                pool_name="image-test",
                slot_size_bytes=64 * 1024,
                slot_count=4,
            ),
        ),
    )
    buffer_broker = LocalBufferBrokerProcessSupervisor(settings=buffer_settings)
    preview_buffer_writer = DirectMmapLocalBufferWriter(buffer_settings)
    fake_supervisor = _FakePreviewSupervisor(
        dataset_storage=dataset_storage,
        preview_buffer_writer=preview_buffer_writer,
    )
    dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id="test-daemon",
        bindings_by_task_type={
            "detection": InferenceControlBinding(
                sync_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_gateway_registry=_FakeRegistry(),
            )
        },
        poll_interval_seconds=0.01,
    )
    mmap_path = tmp_path / "preview" / "inference.mmap"
    captured_mmap_results: list[dict[str, object]] = []

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        result = dispatcher.handle_local_mmap_request(payload)
        captured_mmap_results.append(result)
        return result

    mmap_server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=handle_request,
        slot_count=4,
        slot_payload_capacity_bytes=64 * 1024,
    )
    mmap_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        local_buffer_reader=buffer_broker,
        local_mmap_client=mmap_client,
    )

    buffer_broker.start()
    expiring_lease = buffer_broker.allocate_buffer(
        size=12,
        owner_kind="test",
        owner_id="expiring-preview",
        pool_name="image-test",
        ttl_seconds=1.0,
    )
    try:
        with pytest.raises(InvalidRequestError, match="剩余有效期不足"):
            preview_buffer_writer.write_lease_bytes(
                lease=expiring_lease,
                content=b"abcdefghijkl",
            )
    finally:
        buffer_broker.release(
            expiring_lease.lease_id,
            pool_name=expiring_lease.pool_name,
        )
    mmap_server.start()
    try:
        preview_result = client.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_image_payload=_buffer_image_payload(tmp_path),
                score_threshold=0.25,
                save_result_image=True,
            ),
        )
        inline_result = client.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_image_bytes=b"abcdefghijkl",
                score_threshold=0.25,
                save_result_image=False,
            ),
        )
        dataset_storage.write_bytes("inputs/source.raw", b"abcdefghijkl")
        object_store_result = client.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_uri="inputs/source.raw",
                score_threshold=0.25,
                save_result_image=False,
            ),
        )
        absolute_image_path = tmp_path / "absolute-input.bmp"
        absolute_image_path.write_bytes(b"abcdefghijkl")
        absolute_path_result = client.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_image_payload={
                    "transport_kind": "local-path",
                    "local_path": str(absolute_image_path.resolve()),
                    "media_type": "image/bmp",
                },
                score_threshold=0.25,
                save_result_image=False,
            ),
        )
        timeout_client = QueueBackedInferenceControlClient(
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
            runtime_mode="sync",
            service_id="test-daemon",
            request_timeout_seconds=0.1,
            startup_timeout_seconds=0.1,
            local_buffer_reader=buffer_broker,
            local_mmap_client=_TimeoutMmapClient(),  # type: ignore[arg-type]
        )
        with pytest.raises(OperationTimeoutError, match="mmap 响应超时"):
            timeout_client.run_inference(
                config=config,
                request=DetectionPredictionRequest(
                    input_image_bytes=b"abcdefghijkl",
                    score_threshold=0.25,
                    save_result_image=True,
                ),
            )
        retained_pool_status = buffer_broker.get_status()["pools"][0]
    finally:
        mmap_client.close()
        mmap_server.stop()
        buffer_broker.stop()

    assert preview_result.instance_id == "instance-mmap"
    assert preview_result.execution_result.preview_image_bytes == _one_pixel_png()
    assert inline_result.execution_result.preview_image_bytes is None
    assert object_store_result.execution_result.preview_image_bytes is None
    assert absolute_path_result.execution_result.preview_image_bytes is None
    assert fake_supervisor.actions == ["infer", "infer", "infer", "infer"]
    assert retained_pool_status["used_count"] == 2
    assert retained_pool_status["active_count"] == 1
    assert retained_pool_status["writing_count"] == 1
    assert len(captured_mmap_results) == 4
    for result in captured_mmap_results:
        execution_result = result["execution_result"]
        assert isinstance(execution_result, dict)
        assert "preview_image_bytes_base64" not in execution_result
    assert not dataset_storage.resolve("runtime/inputs/inference-control").exists()


def test_segmentation_response_uses_mmap_v1_overflow_capability(
    tmp_path: Path,
) -> None:
    """验证 segmentation 结构化结果统一使用 mmap v1。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    detection_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    target = replace(detection_target, task_type="segmentation")
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-segmentation",
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    fake_supervisor = _FakeSegmentationSupervisor(dataset_storage=dataset_storage)
    dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id="test-daemon",
        bindings_by_task_type={
            "segmentation": InferenceControlBinding(
                sync_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_gateway_registry=_FakeRegistry(),
            )
        },
        poll_interval_seconds=0.01,
    )
    mmap_path = tmp_path / "segmentation" / "inference.mmap"
    mmap_server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=dispatcher.handle_local_mmap_request,
        slot_count=4,
        slot_payload_capacity_bytes=64 * 1024,
    )
    mmap_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        local_mmap_client=mmap_client,
    )

    mmap_server.start()
    try:
        result = client.run_inference(
            config=config,
            request=SegmentationPredictionRequest(
                input_image_payload=_buffer_image_payload(tmp_path),
                score_threshold=0.25,
                mask_threshold=0.5,
                save_result_image=False,
            ),
        )
        response_metrics = mmap_server.get_health_summary()["response_metrics"]
    finally:
        mmap_client.close()
        mmap_server.stop()

    assert result.instance_id == "instance-segmentation"
    assert len(result.execution_result.instances) == 1
    assert (
        response_metrics["raw_size_bytes_by_task_type"]["segmentation"]["sample_count"]
        == 1
    )
    assert fake_supervisor.actions == ["infer"]


def test_local_mmap_hot_path_keeps_buffer_ref_and_handles_eighty_calls(
    tmp_path: Path,
) -> None:
    """验证 80 路调用不编码图片、不落 ObjectStore 且共用跨平台 mmap mailbox。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-mmap",
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    fake_supervisor = _FakeRefSupervisor(dataset_storage=dataset_storage)
    dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id="test-daemon",
        bindings_by_task_type={
            "detection": InferenceControlBinding(
                sync_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_gateway_registry=_FakeRegistry(),
            )
        },
    )
    mmap_path = tmp_path / "buffers" / "inference-control.mmap"
    mmap_server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=dispatcher.handle_local_mmap_request,
        slot_count=96,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=16,
        poll_interval_seconds=0.0005,
    )
    mmap_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
        poll_interval_seconds=0.0005,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        local_mmap_client=mmap_client,
    )
    buffer_ref = BufferRef(
        buffer_id="buffer-1",
        lease_id="lease-1",
        path=str(tmp_path / "buffers" / "image.dat"),
        offset=0,
        size=12,
        shape=(2, 2, 3),
        dtype="uint8",
        layout="HWC",
        pixel_format="BGR",
        media_type="image/raw",
        broker_epoch="epoch-1",
        generation=1,
    )
    request = DetectionPredictionRequest(
        input_image_payload={
            "transport_kind": "buffer",
            "media_type": "image/raw",
            "buffer_ref": buffer_ref.model_dump(mode="json"),
        },
        score_threshold=0.25,
        save_result_image=False,
    )

    mmap_server.start()
    started_at = perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=32) as executor:
            executions = tuple(
                executor.map(
                    lambda _: client.run_inference(config=config, request=request),
                    range(80),
                )
            )
    finally:
        mmap_client.close()
        mmap_server.stop()

    elapsed_seconds = perf_counter() - started_at
    assert len(executions) == 80
    assert all(item.instance_id == "instance-mmap" for item in executions)
    assert fake_supervisor.actions == ["infer"] * 80
    assert elapsed_seconds < 2.0
    assert not (Path(queue_backend.root_dir) / "inference-control-test-daemon").exists()
    staged_root = dataset_storage.resolve("runtime/inputs/inference-control")
    assert not staged_root.exists()


def test_direct_mmap_reader_reads_only_configured_pool_range(tmp_path: Path) -> None:
    """验证 daemon worker 可直接读取 broker mmap，且不能借 ref 读取任意路径。"""

    root_dir = tmp_path / "buffers"
    pool_dir = root_dir / "image-test"
    pool_dir.mkdir(parents=True)
    pool_path = pool_dir / "image-test.dat"
    pool_path.write_bytes(b"abcdefghijkl" + bytes(116))
    settings = LocalBufferBrokerSettings(
        root_dir=str(root_dir),
        default_pool_name="image-test",
        pools=(
            LocalBufferBrokerPoolSettings(
                pool_name="image-test",
                slot_size_bytes=64,
                slot_count=2,
                file_name=pool_path.name,
            ),
        ),
    )
    reader = DirectMmapLocalBufferReader(settings)
    valid_ref = BufferRef(
        buffer_id="buffer-1",
        lease_id="lease-1",
        path=str(pool_path),
        offset=0,
        size=12,
        media_type="image/raw",
        broker_epoch="epoch-1",
        generation=1,
    )

    try:
        raw_view = reader.read_buffer_ref(valid_ref)
        assert isinstance(raw_view, memoryview)
        assert raw_view.readonly is True
        assert bytes(raw_view) == b"abcdefghijkl"
        encoded_view = reader.read_buffer_ref(
            valid_ref.model_copy(update={"media_type": "image/png"})
        )
        assert isinstance(encoded_view, memoryview)
        assert bytes(encoded_view) == b"abcdefghijkl"
        with pytest.raises(InvalidRequestError, match="不属于已配置 mmap pool"):
            reader.read_buffer_ref(
                valid_ref.model_copy(update={"path": str(tmp_path / "outside.dat")})
            )
    finally:
        reader.close()


def test_local_mmap_hot_path_crosses_independent_spawn_process(tmp_path: Path) -> None:
    """验证 Windows、Linux 和 macOS 共用的 spawn+mmap 独立进程链路。"""

    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    stop_event = context.Event()
    mmap_path = tmp_path / "cross-process" / "inference.mmap"
    process = context.Process(
        target=_run_mmap_echo_server,
        kwargs={
            "path": str(mmap_path),
            "ready_queue": ready_queue,
            "stop_event": stop_event,
        },
        name="test-inference-local-mmap-server",
    )
    process.start()
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
        poll_interval_seconds=0.0005,
    )
    try:
        assert ready_queue.get(timeout=30.0) == {"ready": True}
        with ThreadPoolExecutor(max_workers=32) as executor:
            responses = tuple(
                executor.map(lambda value: client.request({"value": value}), range(80))
            )
        assert [response["result"]["value"] for response in responses] == list(
            range(80)
        )
    finally:
        client.close()
        stop_event.set()
        process.join(timeout=10.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5.0)

    assert process.exitcode == 0


def test_local_mmap_client_mapping_survives_daemon_server_restart(
    tmp_path: Path,
) -> None:
    """验证 daemon 重启后 backend-service 已映射的 mailbox 可继续使用。"""

    mmap_path = tmp_path / "restart" / "inference.mmap"
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=2.0,
        poll_interval_seconds=0.0005,
    )

    def build_server() -> InferenceLocalMmapServer:
        return InferenceLocalMmapServer(
            path=mmap_path,
            request_handler=lambda payload: {"value": payload.get("value")},
            slot_count=8,
            slot_payload_capacity_bytes=64 * 1024,
            max_concurrent_requests=2,
            poll_interval_seconds=0.0005,
        )

    first_server = build_server()
    first_server.start()
    try:
        assert client.request({"value": "before"})["result"] == {"value": "before"}
    finally:
        first_server.stop()

    second_server = build_server()
    second_server.start()
    try:
        assert client.request({"value": "after"})["result"] == {"value": "after"}
    finally:
        client.close()
        second_server.stop()


def test_local_mmap_v1_stop_invalidates_epoch_before_waiting_for_handler(
    tmp_path: Path,
) -> None:
    """验证 daemon 停机立即取消等待请求，不让 client 等到业务超时。"""

    mmap_path = tmp_path / "stop-epoch" / "inference.mmap"
    handler_started = Event()
    release_handler = Event()

    def blocking_handler(_payload: dict[str, object]) -> dict[str, object]:
        handler_started.set()
        assert release_handler.wait(timeout=5.0)
        return {"value": "late"}

    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=blocking_handler,
        slot_count=2,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    stopper = Thread(target=server.stop)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            request_future = executor.submit(client.request, {"value": "blocked"})
            assert handler_started.wait(timeout=2.0)
            stopper.start()
            with pytest.raises(OperationCancelledError):
                request_future.result(timeout=1.0)
    finally:
        release_handler.set()
        if stopper.ident is not None:
            stopper.join(timeout=5.0)
        client.close()
        if server.is_running:
            server.stop()

    assert not stopper.is_alive()


def test_local_mmap_v1_uses_fixed_overflow_pages_and_reclaims_after_ack(
    tmp_path: Path,
) -> None:
    """验证大结果跨多个固定页传输，ACK 后由 daemon 完整回收。"""

    mmap_path = tmp_path / "overflow" / "inference.mmap"
    expected_value = os.urandom(96 * 1024).hex()
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda _payload: {"value": expected_value},
        slot_count=2,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=8,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=4,
        compression_threshold_bytes=1024 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=2.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        response = client.request(
            {
                "action": "infer",
                "process_config": {
                    "runtime_target_snapshot": {"task_type": "detection"}
                },
            }
        )
        deadline = perf_counter() + 1.0
        while server._count_free_pages() != 8 and perf_counter() < deadline:
            sleep(0.001)
        free_page_count = server._count_free_pages()
    finally:
        client.close()
        server.stop()

    assert response == {"ok": True, "result": {"value": expected_value}}
    assert server._page_pool_high_watermark == 4
    assert free_page_count == 8


def test_local_mmap_v1_preserves_exact_payloads_across_all_capacity_boundaries(
    tmp_path: Path,
) -> None:
    """验证 512 KiB 边界及 1/8/16/32 MiB page chain 均无损。"""

    mmap_path = tmp_path / "capacity-boundaries" / "inference.mmap"
    envelope_size = len(
        json.dumps(
            {"ok": True, "result": {"value": ""}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        target_size = int(payload["target_size"])
        return {"value": "x" * (target_size - envelope_size)}

    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=handle_request,
        slot_count=2,
        slot_payload_capacity_bytes=512 * 1024,
        overflow_page_count=64,
        overflow_page_capacity_bytes=512 * 1024,
        max_overflow_pages_per_response=64,
        compression_threshold_bytes=64 * 1024 * 1024,
        max_concurrent_requests=2,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=30.0,
        poll_interval_seconds=0.0005,
    )
    target_sizes = (
        512 * 1024 - 1,
        512 * 1024,
        512 * 1024 + 1,
        1 * 1024 * 1024,
        8 * 1024 * 1024,
        16 * 1024 * 1024,
        32 * 1024 * 1024,
    )
    server.start()
    try:
        for target_size in target_sizes:
            response = client.request({"target_size": target_size})
            value = response["result"]["value"]
            assert isinstance(value, str)
            assert len(value.encode("utf-8")) + envelope_size == target_size
            deadline = perf_counter() + 2.0
            while (
                server._count_free_pages() != server.overflow_page_count
                and perf_counter() < deadline
            ):
                sleep(0.001)
            assert server._count_free_pages() == server.overflow_page_count
    finally:
        client.close()
        server.stop()

    assert server._page_pool_high_watermark == 64


def test_local_mmap_v1_handles_sixteen_mixed_inline_and_paged_requests(
    tmp_path: Path,
) -> None:
    """验证 16 路并发小响应与多页响应互不阻塞或串扰。"""

    mmap_path = tmp_path / "mixed-concurrency" / "inference.mmap"
    large_value = os.urandom(48 * 1024).hex()

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        sleep(0.01)
        return {
            "request_index": payload["request_index"],
            "value": large_value if payload.get("large") is True else "inline",
        }

    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=handle_request,
        slot_count=16,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=64,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=4,
        compression_threshold_bytes=1024 * 1024,
        max_concurrent_requests=16,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = tuple(
                executor.submit(
                    client.request,
                    {"request_index": index, "large": index % 2 == 1},
                )
                for index in range(16)
            )
            responses = tuple(future.result(timeout=10.0) for future in futures)
        deadline = perf_counter() + 2.0
        while server._count_free_pages() != 64 and perf_counter() < deadline:
            sleep(0.001)
        free_page_count = server._count_free_pages()
    finally:
        client.close()
        server.stop()

    for index, response in enumerate(responses):
        assert response["result"]["request_index"] == index
        assert response["result"]["value"] == (
            large_value if index % 2 == 1 else "inline"
        )
    assert server._page_pool_high_watermark >= 2
    assert free_page_count == 64


def test_local_mmap_v1_compresses_repetitive_payload_before_page_allocation(
    tmp_path: Path,
) -> None:
    """验证高压缩率结构化结果保留在内联区，不占用页池。"""

    mmap_path = tmp_path / "compression" / "inference.mmap"
    expected_value = "segment-point," * 20_000
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda _payload: {"value": expected_value},
        slot_count=2,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=8,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=8,
        compression_threshold_bytes=64 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=2.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        response = client.request({"action": "infer"})
    finally:
        client.close()
        server.stop()

    assert response == {"ok": True, "result": {"value": expected_value}}
    assert server._page_pool_high_watermark == 0


def test_local_mmap_v1_uses_fragmented_free_pages_without_contiguous_requirement(
    tmp_path: Path,
) -> None:
    """验证页池碎片化时按序号组合非连续页，不要求物理连续。"""

    server = InferenceLocalMmapServer(
        path=tmp_path / "fragmented" / "inference.mmap",
        request_handler=lambda payload: payload,
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=4,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=4,
    )
    server.start()
    allocations: list[list[int]] = []
    fragmented: list[int] = []
    try:
        for index in range(4):
            allocations.append(
                server._allocate_pages(
                    slot_index=index,
                    generation=index + 1,
                    owner_token=index + 10,
                    page_count=1,
                )
            )
        server._free_pages(allocations[1])
        server._free_pages(allocations[3])
        fragmented = server._allocate_pages(
            slot_index=9,
            generation=9,
            owner_token=99,
            page_count=2,
        )
        assert fragmented == [1, 3]
    finally:
        server._free_pages(allocations[0] if allocations else [])
        server._free_pages(allocations[2] if len(allocations) > 2 else [])
        server._free_pages(fragmented)
        free_page_count = server._count_free_pages()
        server.stop()

    assert free_page_count == 4


def test_local_mmap_v1_pool_exhaustion_is_explicit_and_does_not_block_inline(
    tmp_path: Path,
) -> None:
    """验证页池满载立即返回明确错误，内联请求和回收后请求仍可执行。"""

    mmap_path = tmp_path / "pool-exhaustion" / "inference.mmap"
    large_value = os.urandom(40 * 1024).hex()
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda payload: (
            {"value": large_value}
            if payload.get("large") is True
            else {"value": "inline"}
        ),
        slot_count=2,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=2,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=2,
        compression_threshold_bytes=1024 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=2.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    occupied = server._allocate_pages(
        slot_index=99,
        generation=1,
        owner_token=99,
        page_count=2,
    )
    try:
        exhausted = client.request({"large": True})
        inline = client.request({"large": False})
        health = client.request({"action": "ping", "large": False})
        server._free_pages(occupied)
        occupied = []
        recovered = client.request({"large": True})
    finally:
        server._free_pages(occupied)
        client.close()
        server.stop()

    assert exhausted["ok"] is False
    assert exhausted["error"]["error_code"] == "mmap_response_capacity_exhausted"
    assert exhausted["error"]["status_code"] == 503
    assert "固定溢出页池暂时不足" in exhausted["error"]["error_message"]
    assert inline == {"ok": True, "result": {"value": "inline"}}
    assert health["result"]["mailbox"]["protocol_version"] == 1
    assert health["result"]["mailbox"]["free_overflow_page_count"] == 0
    assert health["result"]["mailbox"]["max_response_bytes"] == 128 * 1024
    assert (
        health["result"]["mailbox"]["response_metrics"]["capacity_exhausted_count"] == 1
    )
    assert recovered == {"ok": True, "result": {"value": large_value}}


def test_local_mmap_v1_rejects_response_above_configured_page_limit(
    tmp_path: Path,
) -> None:
    """验证单请求超过固定页上限时返回容量错误，不扩容或改走其他通道。"""

    mmap_path = tmp_path / "response-limit" / "inference.mmap"
    oversized_value = os.urandom(80 * 1024).hex()
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda _payload: {"value": oversized_value},
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=2,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=2,
        compression_threshold_bytes=1024 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=2.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        response = client.request({"action": "infer"})
    finally:
        client.close()
        server.stop()

    assert response["ok"] is False
    assert response["error"]["error_code"] == "mmap_response_capacity_exhausted"
    assert response["error"]["status_code"] == 503
    assert "超过固定页池单请求上限" in response["error"]["error_message"]


def test_local_mmap_v1_allocator_never_reuses_authoritatively_owned_page(
    tmp_path: Path,
) -> None:
    """验证损坏的 FREE page header 不会覆盖仍由 daemon 登记的响应页。"""

    server = InferenceLocalMmapServer(
        path=tmp_path / "authoritative-page-allocation" / "inference.mmap",
        request_handler=lambda payload: payload,
        slot_count=2,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=2,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=2,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        first = server._allocate_pages(
            slot_index=0,
            generation=11,
            owner_token=101,
            page_count=2,
        )
        assert first == [0, 1]
        view = server._mmap
        assert view is not None
        inference_local_mmap_module._PAGE_STATE.pack_into(
            view,
            server._page_offset(first[0]),
            inference_local_mmap_module._PAGE_FREE,
        )

        assert server._count_free_pages() == 0
        assert (
            server._allocate_pages(
                slot_index=1,
                generation=12,
                owner_token=102,
                page_count=1,
            )
            == []
        )

        server._free_pages_for_owner(0, 11, 101)
        assert server._count_free_pages() == 2
    finally:
        server.stop()


def test_local_mmap_v1_keeps_larger_inline_capacity_as_response_limit(
    tmp_path: Path,
) -> None:
    """验证内联区大于分页上限时仍可完整返回内联结构化结果。"""

    mmap_path = tmp_path / "inline-response-limit" / "inference.mmap"
    value = "x" * (90 * 1024)
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda _payload: {"value": value},
        slot_count=1,
        slot_payload_capacity_bytes=128 * 1024,
        overflow_page_count=2,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=1,
        compression_threshold_bytes=1024 * 1024,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=2.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        response = client.request({"action": "infer"})
        health = server.get_health_summary()
    finally:
        client.close()
        server.stop()

    assert response == {"ok": True, "result": {"value": value}}
    assert health["max_response_bytes"] == 128 * 1024
    assert health["overflow_page_high_watermark"] == 0


def test_local_mmap_v1_restart_reclaims_orphaned_overflow_pages(
    tmp_path: Path,
) -> None:
    """验证 daemon 重启会初始化固定页池并清除上个 epoch 的孤儿页。"""

    mmap_path = tmp_path / "page-restart" / "inference.mmap"

    def build_server() -> InferenceLocalMmapServer:
        return InferenceLocalMmapServer(
            path=mmap_path,
            request_handler=lambda payload: {"value": payload.get("value")},
            slot_count=1,
            slot_payload_capacity_bytes=64 * 1024,
            overflow_page_count=4,
            overflow_page_capacity_bytes=64 * 1024,
            max_overflow_pages_per_response=4,
        )

    first = build_server()
    first.start()
    orphaned = first._allocate_pages(
        slot_index=0,
        generation=1,
        owner_token=1,
        page_count=3,
    )
    assert orphaned == [0, 1, 2]
    assert first._count_free_pages() == 1
    first.stop()

    second = build_server()
    second.start()
    try:
        assert second._count_free_pages() == 4
    finally:
        second.stop()


def test_local_mmap_v1_daemon_crash_mid_page_write_is_recovered_on_restart(
    tmp_path: Path,
) -> None:
    """验证 daemon 在多页写入中退出后，新 epoch 清理半写页和 descriptor。"""

    context = multiprocessing.get_context("spawn")
    ready_event = context.Event()
    page_written_event = context.Event()
    mmap_path = tmp_path / "mid-page-crash" / "inference.mmap"
    crashing_process = context.Process(
        target=_run_crashing_page_server,
        kwargs={
            "path": str(mmap_path),
            "ready_event": ready_event,
            "page_written_event": page_written_event,
        },
        name="test-inference-mmap-mid-page-crash",
    )
    crashing_process.start()
    assert ready_event.wait(timeout=15.0)
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=0.5,
        poll_interval_seconds=0.0005,
    )
    try:
        with pytest.raises(OperationTimeoutError, match="mmap 响应超时"):
            client.request({"action": "infer"})
        assert page_written_event.wait(timeout=5.0)
        crashing_process.join(timeout=5.0)
        assert crashing_process.exitcode == 91

        replacement = InferenceLocalMmapServer(
            path=mmap_path,
            request_handler=lambda payload: {"value": payload.get("value")},
            slot_count=1,
            slot_payload_capacity_bytes=64 * 1024,
            overflow_page_count=4,
            overflow_page_capacity_bytes=64 * 1024,
            max_overflow_pages_per_response=4,
            compression_threshold_bytes=1024 * 1024,
            poll_interval_seconds=0.0005,
        )
        replacement.start()
        try:
            response = client.request({"value": "recovered"})
            assert response == {"ok": True, "result": {"value": "recovered"}}
            deadline = perf_counter() + 2.0
            while (
                replacement.get_health_summary()["descriptor_states"]["free"] != 1
                and perf_counter() < deadline
            ):
                sleep(0.001)
            assert replacement._count_free_pages() == 4
            assert replacement.get_health_summary()["descriptor_states"]["free"] == 1
        finally:
            replacement.stop()
    finally:
        client.close()
        if crashing_process.is_alive():
            crashing_process.terminate()
            crashing_process.join(timeout=5.0)


def test_local_mmap_v1_rejects_corrupted_page_and_reclaims_after_ack(
    tmp_path: Path,
) -> None:
    """验证页 CRC 失败不会交付半损坏结果，client ACK 后立即回收。"""

    mmap_path = tmp_path / "page-corruption" / "inference.mmap"
    large_value = os.urandom(48 * 1024).hex()
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda _payload: {"value": large_value},
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=4,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=4,
        compression_threshold_bytes=1024 * 1024,
        poll_interval_seconds=0.0005,
    )
    original_write_pages = server._write_pages

    def write_corrupted_pages(**kwargs) -> None:
        original_write_pages(**kwargs)
        page_indexes = kwargs["page_indexes"]
        view = server._mmap
        assert isinstance(page_indexes, list) and page_indexes
        assert view is not None
        page_body_offset = (
            server._page_offset(page_indexes[0])
            + server.page_stride
            - server.overflow_page_capacity_bytes
        )
        view[page_body_offset] ^= 0xFF

    server._write_pages = write_corrupted_pages  # type: ignore[method-assign]
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=0.5,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        with pytest.raises(ServiceConfigurationError, match="溢出页校验失败"):
            client.request({"action": "infer"})
        deadline = perf_counter() + 2.0
        while server._count_free_pages() != 4 and perf_counter() < deadline:
            sleep(0.005)
        assert server._count_free_pages() == 4
        assert server.get_health_summary()["descriptor_states"]["free"] == 1
    finally:
        client.close()
        server.stop()


@pytest.mark.parametrize(
    ("corruption_kind", "expected_message"),
    (
        ("cycle", "page chain 循环或越界"),
        ("generation", "溢出页身份不合法"),
        ("owner", "溢出页身份不合法"),
    ),
)
def test_local_mmap_v1_isolates_corrupted_chain_identity_without_page_leak(
    tmp_path: Path,
    corruption_kind: str,
    expected_message: str,
) -> None:
    """验证循环链及 generation/owner 损坏只终止当前响应且页仍可回收。"""

    mmap_path = tmp_path / f"page-{corruption_kind}" / "inference.mmap"
    large_value = os.urandom(48 * 1024).hex()
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda _payload: {"value": large_value},
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=4,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=4,
        compression_threshold_bytes=1024 * 1024,
        poll_interval_seconds=0.0005,
    )
    original_write_pages = server._write_pages

    def write_corrupted_pages(**kwargs) -> None:
        original_write_pages(**kwargs)
        page_indexes = kwargs["page_indexes"]
        view = server._mmap
        assert isinstance(page_indexes, list) and len(page_indexes) >= 2
        assert view is not None
        page_offset = server._page_offset(page_indexes[0])
        header = list(
            inference_local_mmap_module._PAGE_HEADER.unpack_from(view, page_offset)
        )
        if corruption_kind == "cycle":
            header[inference_local_mmap_module._PAGE_NEXT_INDEX] = page_indexes[0]
        elif corruption_kind == "generation":
            header[inference_local_mmap_module._PAGE_GENERATION_INDEX] += 1
        else:
            header[inference_local_mmap_module._PAGE_OWNER_INDEX] += 1
        inference_local_mmap_module._PAGE_HEADER.pack_into(
            view,
            page_offset,
            *header,
        )

    server._write_pages = write_corrupted_pages  # type: ignore[method-assign]
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=1.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        with pytest.raises(ServiceConfigurationError, match=expected_message):
            client.request({"action": "infer"})
        deadline = perf_counter() + 2.0
        while server._count_free_pages() != 4 and perf_counter() < deadline:
            sleep(0.005)
        assert server._count_free_pages() == 4
        assert server.get_health_summary()["descriptor_states"]["free"] == 1
    finally:
        client.close()
        server.stop()


def test_local_mmap_v1_reclaims_unacked_response_after_client_exit(
    tmp_path: Path,
) -> None:
    """验证 client 读取分页响应后退出且未 ACK 时 daemon 有界回收资源。"""

    mmap_path = tmp_path / "unacked-client" / "inference.mmap"
    large_value = os.urandom(48 * 1024).hex()
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda _payload: {"value": large_value},
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        overflow_page_count=4,
        overflow_page_capacity_bytes=64 * 1024,
        max_overflow_pages_per_response=4,
        compression_threshold_bytes=1024 * 1024,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=0.5,
        poll_interval_seconds=0.0005,
    )
    server.start()
    view = client._require_open()
    server_epoch = server._server_epoch
    owner_token = 928_374
    deadline_ns = monotonic_ns() + 500_000_000
    slot_index, lock_path = client._claim_slot(
        view=view,
        server_epoch=server_epoch,
        owner_token=owner_token,
        deadline_ns=deadline_ns,
    )
    generation = client._write_request(
        view=view,
        slot_index=slot_index,
        lock_path=lock_path,
        server_epoch=server_epoch,
        owner_token=owner_token,
        encoded_request=b'{"action":"infer"}',
        deadline_ns=deadline_ns,
    )
    response = client._wait_response(
        view=view,
        slot_index=slot_index,
        generation=generation,
        server_epoch=server_epoch,
        owner_token=owner_token,
        deadline_ns=deadline_ns,
    )
    assert response == {"ok": True, "result": {"value": large_value}}
    assert server._count_free_pages() == 2

    client.close()
    try:
        deadline = perf_counter() + 2.0
        while server._count_free_pages() != 4 and perf_counter() < deadline:
            sleep(0.005)
        assert server._count_free_pages() == 4
        assert server.get_health_summary()["descriptor_states"]["free"] == 1
        assert not lock_path.exists()
    finally:
        server.stop()


def test_local_mmap_rejects_second_server_for_same_mailbox(tmp_path: Path) -> None:
    """验证同一 mailbox 只能由一个 daemon 实例初始化和回收。"""

    mmap_path = tmp_path / "single-server" / "inference.mmap"
    first_server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda payload: {"value": payload.get("value")},
        slot_count=4,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=2,
    )
    second_server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda payload: {"value": payload.get("value")},
        slot_count=4,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=2,
    )

    first_server.start()
    try:
        with pytest.raises(ServiceConfigurationError, match="另一个 daemon"):
            second_server.start()
    finally:
        second_server.stop()
        first_server.stop()


def test_local_mmap_timeout_slot_is_reclaimed_for_next_request(tmp_path: Path) -> None:
    """验证超时中的 handler 完成后回收 slot，不污染后续推理。"""

    mmap_path = tmp_path / "timeout" / "inference.mmap"

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        if payload.get("slow") is True:
            sleep(0.2)
        return {"value": payload.get("value")}

    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=handle_request,
        slot_count=8,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=2,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=0.1,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        with pytest.raises(OperationTimeoutError, match="mmap 响应超时"):
            client.request({"slow": True, "value": "discarded"})
        sleep(0.25)
        response = client.request({"value": "next"})
        assert response["result"] == {"value": "next"}
    finally:
        client.close()
        server.stop()


def test_local_mmap_reclaims_expired_claim_before_request_publication(
    tmp_path: Path,
) -> None:
    """验证 client 发布前崩溃留下的过期 FREE slot 锁不会永久降低容量。"""

    mmap_path = tmp_path / "abandoned-claim" / "inference.mmap"
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda payload: {"value": payload.get("value")},
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=2.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    lock_path = mmap_path.with_name(f"{mmap_path.name}.slot-0.lock")
    lock_path.write_text(
        json.dumps(
            {
                "pid": 999999,
                "owner_token": 1,
                "server_epoch": 1,
                "deadline_ns": monotonic_ns() - 1,
            }
        ),
        encoding="utf-8",
    )
    try:
        assert client.request({"value": "recovered"})["result"] == {
            "value": "recovered"
        }
    finally:
        client.close()
        server.stop()


def test_local_mmap_cancelled_active_slot_is_not_reused_by_next_client(
    tmp_path: Path,
) -> None:
    """验证超时 handler 未退出前，同一槽位不会被下一代请求复用或覆盖。"""

    mmap_path = tmp_path / "cancelled-active" / "inference.mmap"

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        if payload.get("slow") is True:
            sleep(0.25)
        return {"value": payload.get("value")}

    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=handle_request,
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    timing_out_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=0.1,
        poll_interval_seconds=0.0005,
    )
    next_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=1.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        with pytest.raises(OperationTimeoutError, match="mmap 响应超时"):
            timing_out_client.request({"slow": True, "value": "expired"})
        response = next_client.request({"value": "next-generation"})
        assert response["result"] == {"value": "next-generation"}
    finally:
        timing_out_client.close()
        next_client.close()
        server.stop()


def test_local_mmap_deadline_race_never_reuses_slot_generation(
    tmp_path: Path,
) -> None:
    """验证 deadline 边界连续回收不会覆盖下一代请求。"""

    mmap_path = tmp_path / "deadline-race" / "inference.mmap"

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        if payload.get("near_deadline") is True:
            sleep(0.105)
        return {"value": payload.get("value")}

    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=handle_request,
        slot_count=1,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=1,
        poll_interval_seconds=0.0005,
    )
    deadline_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=0.1,
        poll_interval_seconds=0.0005,
    )
    next_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=1.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        for index in range(20):
            with pytest.raises(OperationTimeoutError, match="mmap 响应超时"):
                deadline_client.request(
                    {"near_deadline": True, "value": f"expired-{index}"}
                )
            response = next_client.request({"value": f"next-{index}"})
            assert response["result"] == {"value": f"next-{index}"}
    finally:
        deadline_client.close()
        next_client.close()
        server.stop()


def test_local_mmap_concurrent_publication_never_exposes_partial_generation(
    tmp_path: Path,
) -> None:
    """验证高并发两阶段发布不会让 server 读取半写入 header。"""

    mmap_path = tmp_path / "concurrent-publication" / "inference.mmap"
    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=lambda payload: {"value": payload.get("value")},
        slot_count=8,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=8,
        poll_interval_seconds=0.0005,
    )
    client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=5.0,
        poll_interval_seconds=0.0005,
    )
    server.start()
    try:
        with ThreadPoolExecutor(max_workers=32) as executor:
            responses = tuple(
                executor.map(
                    lambda value: client.request({"value": value}),
                    range(1000),
                )
            )
    finally:
        client.close()
        server.stop()

    assert [response["result"]["value"] for response in responses] == list(range(1000))


def test_local_mmap_multi_process_busy_responses_keep_slot_ownership(
    tmp_path: Path,
) -> None:
    """验证多进程成功/满载响应交错时不会误报 slot ownership 丢失。"""

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    mmap_path = tmp_path / "multi-process-busy" / "inference.mmap"
    infer_slots = BoundedSemaphore(2)

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        if not infer_slots.acquire(blocking=False):
            raise InvalidRequestError("当前 deployment 推理线程已满载，请稍后重试")
        try:
            sleep(0.01)
            return {"value": payload.get("value")}
        finally:
            infer_slots.release()

    server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=handle_request,
        slot_count=16,
        slot_payload_capacity_bytes=64 * 1024,
        max_concurrent_requests=8,
        poll_interval_seconds=0.0005,
    )
    processes = tuple(
        context.Process(
            target=_run_busy_mmap_client,
            kwargs={
                "path": str(mmap_path),
                "worker_index": worker_index,
                "request_count": 500,
                "start_event": start_event,
                "result_queue": result_queue,
            },
            name=f"test-inference-mmap-busy-client-{worker_index}",
        )
        for worker_index in range(4)
    )
    server.start()
    try:
        for process in processes:
            process.start()
        start_event.set()
        results = tuple(result_queue.get(timeout=90.0) for _ in processes)
        for process in processes:
            process.join(timeout=15.0)
    finally:
        start_event.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)
        server.stop()

    assert all(process.exitcode == 0 for process in processes)
    assert sum(result["success_count"] for result in results) > 0
    assert sum(result["busy_count"] for result in results) > 0
    assert [error for result in results for error in result["errors"]] == []


def test_inference_control_dispatcher_cleans_abandoned_response_queues(
    tmp_path: Path,
) -> None:
    """验证客户端超时遗留的控制响应队列会按保留期回收。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    queue_name = f"{INFERENCE_CONTROL_RESPONSE_QUEUE_PREFIX}-abandoned"
    queue_backend.enqueue(queue_name=queue_name, payload={"ok": True})
    queue_dir = Path(queue_backend.root_dir) / queue_name
    for path in sorted(queue_dir.rglob("*"), reverse=True):
        os.utime(path, (1.0, 1.0))
    os.utime(queue_dir, (1.0, 1.0))
    dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id="test-daemon",
        bindings_by_task_type={},
        response_queue_retention_seconds=1.0,
    )

    dispatcher._cleanup_response_queues_if_needed()

    assert not queue_dir.exists()


def test_inference_read_path_requires_mmap_without_creating_queue_messages(
    tmp_path: Path,
) -> None:
    """验证只读状态不再回退到持久化队列。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-timeout",
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="missing-daemon",
        request_timeout_seconds=0.1,
        startup_timeout_seconds=0.1,
        control_read_timeout_seconds=0.1,
        availability_probe_timeout_seconds=0.1,
    )

    with pytest.raises(ServiceConfigurationError, match="缺少 mmap v1"):
        client.get_status(config)

    queue_root = Path(queue_backend.root_dir)
    control_pending_dir = queue_root / "inference-control-missing-daemon" / "pending"
    assert not control_pending_dir.exists() or not any(
        control_pending_dir.glob("*.json")
    )
    assert not list(queue_root.glob("inference-control-response-*"))


def test_inference_control_mutations_do_not_use_short_read_timeout(
    tmp_path: Path,
) -> None:
    """验证 reset/stop 使用各自业务超时，不被 status/health 快速窗口截断。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-slow-mutations",
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    fake_supervisor = _SlowMutationSupervisor(dataset_storage=dataset_storage)
    dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id="test-daemon",
        bindings_by_task_type={
            "detection": InferenceControlBinding(
                sync_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_gateway_registry=_FakeRegistry(),
            )
        },
        poll_interval_seconds=0.005,
    )
    mmap_path = tmp_path / "slow-mutations" / "inference.mmap"
    mmap_server = InferenceLocalMmapServer(
        path=mmap_path,
        request_handler=dispatcher.handle_local_mmap_request,
        slot_count=2,
        slot_payload_capacity_bytes=64 * 1024,
    )
    mmap_client = InferenceLocalMmapClient(
        path=mmap_path,
        request_timeout_seconds=0.5,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=0.5,
        startup_timeout_seconds=0.5,
        shutdown_timeout_seconds=0.5,
        control_read_timeout_seconds=0.05,
        availability_probe_timeout_seconds=0.05,
        local_mmap_client=mmap_client,
    )

    dispatcher.start()
    mmap_server.start()
    try:
        assert client.reset_deployment(config).process_state == "running"
        assert client.stop_deployment(config).process_state == "stopped"
    finally:
        mmap_client.close()
        mmap_server.stop()
        dispatcher.stop()

    assert fake_supervisor.actions == ["reset", "stop"]


def test_inference_control_dispatcher_discards_expired_mutating_request(
    tmp_path: Path,
) -> None:
    """验证 daemon 重启后不会回放已经超过 deadline 的 start 请求。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="pytorch",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="model.pt",
        runtime_artifact_file_type="pytorch-state-dict",
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-expired",
        runtime_target=target,
        project_id="project-1",
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    fake_supervisor = _FakeSupervisor(dataset_storage=dataset_storage)
    dispatcher = InferenceControlDispatcher(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        service_id="test-daemon",
        bindings_by_task_type={
            "detection": InferenceControlBinding(
                sync_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_supervisor=fake_supervisor,  # type: ignore[arg-type]
                async_gateway_registry=_FakeRegistry(),
            )
        },
    )
    response_queue_name = "inference-control-response-expired"
    queue_backend.enqueue(
        queue_name="inference-control-test-daemon",
        payload={
            "request_id": "expired-request",
            "action": "start",
            "runtime_mode": "sync",
            "response_queue_name": response_queue_name,
            "expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat(),
            "process_config": _serialize_process_config(config),
        },
        metadata={"request_id": "expired-request"},
    )
    message = queue_backend.claim_next(
        queue_name="inference-control-test-daemon",
        worker_id="test-worker",
    )
    assert message is not None

    dispatcher._process_message(message)

    stored = queue_backend.get_task(
        queue_name="inference-control-test-daemon",
        task_id=message.task_id,
    )
    assert stored is not None
    assert stored.status == "completed"
    assert stored.metadata["discarded"] == "expired"
    assert fake_supervisor.actions == []
    assert not (Path(queue_backend.root_dir) / response_queue_name).exists()


def _status(
    config: DeploymentProcessConfig,
    *,
    desired_state: str,
    process_state: str,
) -> DeploymentProcessStatus:
    """构造固定 deployment status。"""

    return DeploymentProcessStatus(
        deployment_instance_id=config.deployment_instance_id,
        runtime_mode="sync",
        instance_count=1,
        desired_state=desired_state,
        process_state=process_state,
        process_id=1234 if process_state == "running" else None,
        auto_restart=True,
        restart_count=0,
    )


def _health(config: DeploymentProcessConfig) -> DeploymentProcessHealth:
    """构造固定 deployment health。"""

    status = _status(config, desired_state="running", process_state="running")
    return DeploymentProcessHealth(**status.__dict__)


def _one_pixel_png() -> bytes:
    """返回固定的一像素 PNG。"""

    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"
    )


def _buffer_image_payload(tmp_path: Path) -> dict[str, object]:
    """构造无需物化图片内容的 LocalBuffer 引用载荷。"""

    buffer_ref = BufferRef(
        buffer_id="buffer-test",
        lease_id="lease-test",
        path=str(tmp_path / "buffers" / "image.dat"),
        offset=0,
        size=12,
        shape=(2, 2, 3),
        dtype="uint8",
        layout="HWC",
        pixel_format="BGR",
        media_type="image/raw",
        broker_epoch="epoch-test",
        generation=1,
    )
    return {
        "transport_kind": "buffer",
        "media_type": "image/raw",
        "buffer_ref": buffer_ref.model_dump(mode="json"),
    }
