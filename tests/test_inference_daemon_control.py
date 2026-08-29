"""独立 inference daemon 本地控制通道测试。"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from time import perf_counter, sleep
from types import SimpleNamespace

import pytest

from backend.contracts.buffers import BufferRef
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ServiceError,
    ServiceConfigurationError,
)
from backend.service.application.local_buffers import (
    DirectMmapLocalBufferReader,
    DirectMmapLocalBufferWriter,
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
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessBatchExecution,
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
from backend.service.infrastructure.ipc.inference_mailbox import (
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


def test_inference_daemon_parent_import_does_not_load_model_runtimes() -> None:
    """daemon 管理进程导入期不得装入 PyTorch 或五类模型执行实现。"""

    script = """
import sys
import backend.inference_daemon.runtime

unexpected = sorted(
    name
    for name in sys.modules
    if name == "torch"
    or name.startswith("torch.")
    or name.endswith(
        (
            "classification_model_runtime",
            "detection_model_runtime",
            "segmentation_model_runtime",
            "pose_model_runtime",
            "obb_model_runtime",
        )
    )
)
if unexpected:
    raise SystemExit("unexpected heavy imports: " + ",".join(unexpected))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


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


class _TimeoutMessageClient:
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
        assert request.input_image_payload["buffer_ref"]["content_length"] == 12
        return DeploymentProcessExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-mmap",
            execution_result=build_test_execution_result(
                runtime_target=config.runtime_target
            ),
        )

    def run_inference_batch(self, *, config, requests):
        """记录 Batch 并校验每项始终携带 BufferRef。"""

        self.actions.append("infer_batch")
        for request in requests:
            assert request.input_image_bytes is None
            assert request.input_uri is None
            assert request.input_image_payload is not None
            assert request.input_image_payload["transport_kind"] == "buffer"
            assert request.input_image_payload["buffer_ref"]["content_length"] == 12
        return DeploymentProcessBatchExecution(
            deployment_instance_id=config.deployment_instance_id,
            instance_id="instance-mmap-batch",
            execution_results=tuple(
                build_test_execution_result(runtime_target=config.runtime_target)
                for _ in requests
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


def test_inference_ping_reports_reconciler_and_local_buffer_readiness() -> None:
    """mmap probe 必须反映真实依赖状态，不能只证明 mailbox 可往返。"""

    dispatcher = InferenceControlDispatcher(
        queue_backend=SimpleNamespace(),  # type: ignore[arg-type]
        dataset_storage=SimpleNamespace(),  # type: ignore[arg-type]
        service_id="inference-daemon",
        bindings_by_task_type={},
        readiness_provider=lambda: {
            "ready": False,
            "local_buffer": {"ready": False, "error": "broker missing"},
            "initial_reconcile_completed": False,
        },
    )

    assert dispatcher.handle_inference_message_request({"action": "ping"}) == {
        "ready": False,
        "local_buffer": {"ready": False, "error": "broker missing"},
        "initial_reconcile_completed": False,
        "service_id": "inference-daemon",
    }


def _run_mmap_echo_server(
    *, buffers_root: str, service_id: str, ready_queue, stop_event
) -> None:
    """在独立 spawn 进程中运行最小 mmap echo server。"""

    server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id=service_id,
        request_handler=lambda payload: {"value": payload.get("value")},
        max_concurrent_requests=16,
    )
    server.start()
    ready_queue.put({"ready": True})
    try:
        stop_event.wait(timeout=60.0)
    finally:
        server.stop()


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
    buffers_root = tmp_path / "control-round-trip"
    mmap_server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=dispatcher.handle_inference_message_request,
    )
    mmap_client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        message_client=mmap_client,
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


def test_inference_mmap_error_round_trip_preserves_service_error(
    tmp_path: Path,
) -> None:
    """验证 mmap server 的规范错误字段能被真实控制客户端完整恢复。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    buffers_root = tmp_path / "error-round-trip"

    def _raise_capacity_error(_payload: dict[str, object]) -> dict[str, object]:
        raise InvalidRequestError(
            "当前 deployment 推理线程已满载，请稍后重试",
            details={"deployment_instance_id": "deployment-instance-1", "instance_count": 2},
        )

    server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=_raise_capacity_error,
    )
    mmap_client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        message_client=mmap_client,
    )

    server.start()
    try:
        with pytest.raises(ServiceError) as captured:
            client.ping()
    finally:
        mmap_client.close()
        server.stop()

    assert captured.value.code == "invalid_request"
    assert captured.value.message == "当前 deployment 推理线程已满载，请稍后重试"
    assert captured.value.status_code == 400
    assert captured.value.details == {
        "deployment_instance_id": "deployment-instance-1",
        "instance_count": 2,
    }


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
        arena_size_bytes=16 * 1024 * 1024,
        min_block_size_bytes=1024 * 1024,
        max_allocation_bytes=8 * 1024 * 1024,
        reader_guard_slots=4,
    )
    buffer_broker = LocalBufferBrokerProcessSupervisor(
        settings=buffer_settings,
        root_dir=tmp_path / "preview-buffers",
    )
    buffer_broker.start()
    preview_buffer_writer = DirectMmapLocalBufferWriter(
        buffer_settings,
        root_dir=tmp_path / "preview-buffers",
    )
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
    buffers_root = tmp_path / "preview"
    captured_mmap_results: list[dict[str, object]] = []

    def handle_request(payload: dict[str, object]) -> dict[str, object]:
        result = dispatcher.handle_inference_message_request(payload)
        captured_mmap_results.append(result)
        return result

    mmap_server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=handle_request,
    )
    mmap_client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
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
        message_client=mmap_client,
    )

    expiring_lease = buffer_broker.allocate_buffer(
        content_length=12,
        owner_kind="test",
        owner_id="expiring-preview",
        ttl_seconds=1.0,
    )
    try:
        preview_buffer_writer.write_lease_bytes(
            lease=expiring_lease,
            content=b"abcdefghijkl",
        )
    finally:
        buffer_broker.release(expiring_lease.lease_id)
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
            message_client=_TimeoutMessageClient(),  # type: ignore[arg-type]
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
        retained_pool_status = buffer_broker.get_status()
    finally:
        mmap_client.close()
        mmap_server.stop()
        preview_buffer_writer.close()
        buffer_broker.stop()

    assert preview_result.instance_id == "instance-mmap"
    assert preview_result.execution_result.preview_image_bytes == _one_pixel_png()
    assert inline_result.execution_result.preview_image_bytes is None
    assert object_store_result.execution_result.preview_image_bytes is None
    assert absolute_path_result.execution_result.preview_image_bytes is None
    assert fake_supervisor.actions == ["infer", "infer", "infer", "infer"]
    assert retained_pool_status["active_lease_count"] == 2
    general_capacity = retained_pool_status["general"]
    assert isinstance(general_capacity, dict)
    assert general_capacity["active"] >= 1024 * 1024
    assert general_capacity["reserved_writing"] >= 1024 * 1024
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
    buffers_root = tmp_path / "segmentation"
    mmap_server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=dispatcher.handle_inference_message_request,
    )
    mmap_client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        message_client=mmap_client,
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
    buffers_root = tmp_path / "buffers"
    mmap_server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=dispatcher.handle_inference_message_request,
        max_concurrent_requests=16,
    )
    mmap_client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        message_client=mmap_client,
    )
    buffer_ref = BufferRef(
        buffer_id="local-buffer-main:0",
        lease_id="lease-1",
        arena_id="local-buffer-main",
        descriptor_index=0,
        descriptor_generation=1,
        broker_epoch="1" * 32,
        offset=0,
        content_length=12,
        allocation_capacity_bytes=1024 * 1024,
        shape=(2, 2, 3),
        dtype="uint8",
        layout="HWC",
        pixel_format="BGR24",
        media_type="image/raw",
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


def test_queue_backed_client_routes_two_concurrent_batches_over_mmap(
    tmp_path: Path,
) -> None:
    """验证 Workflow 两分支并发 Batch 走 daemon mmap，而不落入基类本地状态。"""

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
        deployment_instance_id="deployment-mmap-batch",
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
    buffers_root = tmp_path / "batch-buffers"
    mmap_server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=dispatcher.handle_inference_message_request,
        max_concurrent_requests=4,
    )
    mmap_client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=5.0,
    )
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
        message_client=mmap_client,
    )
    buffer_ref = BufferRef(
        buffer_id="local-buffer-main:0",
        lease_id="lease-batch",
        arena_id="local-buffer-main",
        descriptor_index=0,
        descriptor_generation=1,
        broker_epoch="1" * 32,
        offset=0,
        content_length=12,
        allocation_capacity_bytes=1024 * 1024,
        shape=(2, 2, 3),
        dtype="uint8",
        layout="HWC",
        pixel_format="BGR24",
        media_type="image/raw",
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
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            executions = tuple(
                executor.map(
                    lambda _: client.run_inference_batch(
                        config=config,
                        requests=(request,) * 12,
                    ),
                    range(2),
                )
            )
        response_metrics = mmap_server.get_health_summary()["response_metrics"]
    finally:
        mmap_client.close()
        mmap_server.stop()

    assert len(executions) == 2
    assert all(item.instance_id == "instance-mmap-batch" for item in executions)
    assert all(len(item.execution_results) == 12 for item in executions)
    assert sorted(fake_supervisor.actions) == ["infer_batch", "infer_batch"]
    assert response_metrics["raw_size_bytes_by_task_type"]["detection"]["sample_count"] == 2


def test_direct_mmap_reader_reads_only_configured_arena_identity(tmp_path: Path) -> None:
    """daemon worker 只读取受信 arena locator，拒绝伪造 identity。"""

    root_dir = tmp_path / "buffers"
    settings = LocalBufferBrokerSettings(
        arena_size_bytes=16 * 1024 * 1024,
        min_block_size_bytes=1024 * 1024,
        max_allocation_bytes=8 * 1024 * 1024,
        reader_guard_slots=4,
    )
    supervisor = LocalBufferBrokerProcessSupervisor(
        settings=settings,
        root_dir=root_dir,
    )
    supervisor.start()
    result = supervisor.write_bytes(
        content=b"abcdefghijkl",
        owner_kind="workflow-runtime",
        owner_id="run-1",
        media_type="image/raw",
    )
    reader = DirectMmapLocalBufferReader(settings, root_dir=root_dir)

    try:
        assert reader.read_buffer_ref(result.buffer_ref) == b"abcdefghijkl"
        with pytest.raises(InvalidRequestError, match="arena identity"):
            reader.read_buffer_ref(
                result.buffer_ref.model_copy(
                    update={"arena_id": "unexpected-arena"}
                )
            )
        with pytest.raises(InvalidRequestError, match="identity"):
            reader.read_buffer_ref(
                result.buffer_ref.model_copy(update={"offset": 1024 * 1024})
            )
    finally:
        reader.close()
        supervisor.stop()


def test_local_mmap_hot_path_crosses_independent_spawn_process(tmp_path: Path) -> None:
    """验证 Windows、Linux 和 macOS 共用的 spawn+mmap 独立进程链路。"""

    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    stop_event = context.Event()
    buffers_root = tmp_path / "cross-process"
    process = context.Process(
        target=_run_mmap_echo_server,
        kwargs={
            "buffers_root": str(buffers_root),
            "service_id": "test-daemon",
            "ready_queue": ready_queue,
            "stop_event": stop_event,
        },
        name="test-inference-local-mmap-server",
    )
    process.start()
    client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=5.0,
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


def test_local_mmap_client_fences_restart_without_retrying_published_request(
    tmp_path: Path,
) -> None:
    """验证 daemon 重启后旧调用报错，下一次独立调用重新打开 Channel。"""

    buffers_root = tmp_path / "restart"
    client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=2.0,
    )

    def build_server() -> InferenceLocalMmapServer:
        return InferenceLocalMmapServer(
            buffers_root=buffers_root,
            service_id="test-daemon",
            request_handler=lambda payload: {"value": payload.get("value")},
            max_concurrent_requests=2,
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
        with pytest.raises(OperationCancelledError):
            client.request({"value": "must-not-retry"})
        assert client.request({"value": "after"})["result"] == {"value": "after"}
    finally:
        client.close()
        second_server.stop()


def test_local_mmap_v1_stop_invalidates_epoch_before_waiting_for_handler(
    tmp_path: Path,
) -> None:
    """验证 daemon 停机立即取消等待请求，不让 client 等到业务超时。"""

    buffers_root = tmp_path / "stop-epoch"
    handler_started = Event()
    release_handler = Event()

    def blocking_handler(_payload: dict[str, object]) -> dict[str, object]:
        handler_started.set()
        assert release_handler.wait(timeout=5.0)
        return {"value": "late"}

    server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=blocking_handler,
        max_concurrent_requests=1,
    )
    client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_timeout_seconds=5.0,
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
    buffers_root = tmp_path / "slow-mutations"
    mmap_server = InferenceLocalMmapServer(
        buffers_root=buffers_root,
        service_id="test-daemon",
        request_handler=dispatcher.handle_inference_message_request,
    )
    mmap_client = InferenceLocalMmapClient(
        buffers_root=buffers_root,
        service_id="test-daemon",
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
        message_client=mmap_client,
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

    del tmp_path
    buffer_ref = BufferRef(
        buffer_id="local-buffer-main:0",
        lease_id="lease-test",
        arena_id="local-buffer-main",
        descriptor_index=0,
        descriptor_generation=1,
        broker_epoch="1" * 32,
        offset=0,
        content_length=12,
        allocation_capacity_bytes=1024 * 1024,
        shape=(2, 2, 3),
        dtype="uint8",
        layout="HWC",
        pixel_format="BGR24",
        media_type="image/raw",
    )
    return {
        "transport_kind": "buffer",
        "media_type": "image/raw",
        "buffer_ref": buffer_ref.model_dump(mode="json"),
    }
