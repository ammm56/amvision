"""独立 inference daemon 本地控制通道测试。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
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
from backend.service.application.errors import OperationTimeoutError
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
