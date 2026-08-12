"""独立 inference daemon 本地控制通道测试。"""

from __future__ import annotations

import json
import os
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic_ns, perf_counter, sleep

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.contracts.buffers import BufferRef
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionRequest,
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
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.local_buffers import (
    DirectMmapLocalBufferReader,
    LocalBufferBrokerPoolSettings,
    LocalBufferBrokerSettings,
)
from backend.service.application.models.inference.inference_gateway import (
    _serialize_process_config,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
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

    def run_inference(self, *, config, request):
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


class _FakeRefSupervisor(_FakeSupervisor):
    """验证 mmap 热路径保持 BufferRef，不读取或物化图片。"""

    def run_inference(self, *, config, request):
        """记录 infer 并校验 task-native request 仍携带 BufferRef。"""

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


class _SlowMutationSupervisor(_FakeSupervisor):
    """模拟 runtime session 释放时间超过只读控制超时的 supervisor。"""

    def stop_deployment(self, config):
        sleep(0.15)
        return super().stop_deployment(config)

    def reset_deployment(self, config):
        sleep(0.15)
        return super().reset_deployment(config)


def _run_mmap_echo_server(
    *, path: str, ready_queue, stop_event
) -> None:
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


def test_queue_backed_inference_control_round_trip_and_stages_image(
    tmp_path: Path,
) -> None:
    """验证控制、状态和大图片数据面不会在 backend-service 创建模型进程。"""

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
    client = QueueBackedInferenceControlClient(
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        runtime_mode="sync",
        service_id="test-daemon",
        request_timeout_seconds=5.0,
        startup_timeout_seconds=5.0,
    )

    dispatcher.start()
    try:
        assert client.ping() == {"ready": True, "service_id": "test-daemon"}
        assert client.start_deployment(config).process_state == "running"
        assert client.get_health(config).process_state == "running"
        result = client.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_image_bytes=_one_pixel_png(),
                score_threshold=0.25,
                save_result_image=False,
            ),
        )
        assert result.instance_id == "instance-1"
        assert len(result.execution_result.detections) == 1
        assert client.stop_deployment(config).process_state == "stopped"
    finally:
        dispatcher.stop()

    assert fake_supervisor.actions == ["start", "health", "infer", "stop"]
    staged_root = dataset_storage.resolve("runtime/inputs/inference-control")
    assert not staged_root.exists() or not any(staged_root.rglob("input.png"))


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

    assert [response["result"]["value"] for response in responses] == list(
        range(1000)
    )


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


def test_inference_control_timeout_removes_pending_request_and_response_queue(
    tmp_path: Path,
) -> None:
    """验证 daemon 不在线时客户端超时不会留下主请求或一次性队列。"""

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

    with pytest.raises(OperationTimeoutError):
        client.get_status(config)

    queue_root = Path(queue_backend.root_dir)
    control_pending_dir = queue_root / "inference-control-missing-daemon" / "pending"
    assert not control_pending_dir.exists() or not any(control_pending_dir.glob("*.json"))
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
    )

    dispatcher.start()
    try:
        assert client.reset_deployment(config).process_state == "running"
        assert client.stop_deployment(config).process_state == "stopped"
    finally:
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
