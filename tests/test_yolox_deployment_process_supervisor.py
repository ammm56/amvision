"""deployment 进程监督器行为测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import pytest

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessSupervisor,
)
import backend.service.application.runtime.deployment.deployment_process_supervisor as deployment_supervisor_module
from backend.service.application.runtime.deployment import cpu_device_resource_manager
from backend.service.application.runtime.deployment.cpu_device_resource_manager import (
    CpuDeviceResourceManager,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionRequest,
)
from backend.service.application.runtime.support.safe_counter import (
    JSON_SAFE_INTEGER_MAX,
)
from backend.service.application.local_buffers import (
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.application.runtime.device_leases import (
    CudaDeviceResource,
    DeviceLeaseMode,
    DeviceLeaseProvider,
    DeviceLeaseProviderConfig,
    DeviceLeaseUnavailableError,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentExecutionPolicy,
    DeploymentRuntimeConfiguration,
    OpenVinoCpuRuntimeOptions,
)
from backend.service.settings import BackendServiceDeploymentProcessSupervisorConfig
from tests.deployment_process_fake_worker import fake_deployment_process_worker


class _StaticCudaResolver:
    """为 deployment 集成测试提供不依赖硬件的 GPU UUID。"""

    resource = CudaDeviceResource(
        cuda_index=0,
        device_name="cuda:0",
        resource_key="GPU-bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
    )

    def list_visible_devices(self, *, torch_module: object | None = None):
        return (self.resource,)

    def resolve(self, device_name: str, *, torch_module: object | None = None):
        assert device_name == "cuda:0"
        return self.resource


@pytest.mark.parametrize("device_name", ("cuda", "cuda:0"))
def test_cuda_runtime_target_requires_lifecycle_reservation(
    tmp_path: Path,
    device_name: str,
) -> None:
    """公开支持的 CUDA device 写法都必须进入 deployment lease 边界。"""

    target = replace(
        _build_runtime_target(tmp_path / "model.pt"),
        runtime_backend="pytorch",
        device_name=device_name,
    )

    assert deployment_supervisor_module._runtime_target_uses_cuda(target) is True


def test_deployment_process_supervisor_supports_lifecycle_and_auto_restart(
    tmp_path: Path,
) -> None:
    """验证 deployment 进程监督器支持启动、推理、停止和崩溃自动拉起。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-supervisor-1",
        runtime_target=_build_runtime_target(runtime_artifact_path),
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2)
        ),
    )
    (tmp_path / "runtime-inputs").mkdir()
    (tmp_path / "runtime-inputs" / "image-1.jpg").write_bytes(b"image-1")
    (tmp_path / "runtime-inputs" / "image-2.jpg").write_bytes(b"image-2")
    buffer_broker = LocalBufferBrokerProcessSupervisor(
        root_dir=tmp_path / "buffers",
        settings=LocalBufferBrokerSettings(
            arena_size_bytes=16 * 1024 * 1024,
            min_block_size_bytes=1024 * 1024,
            max_allocation_bytes=8 * 1024 * 1024,
            reader_guard_slots=4,
        )
    )
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path))
    )
    supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=BackendServiceDeploymentProcessSupervisorConfig(
            auto_restart=True,
            monitor_interval_seconds=0.05,
            request_timeout_seconds=30.0,
            shutdown_timeout_seconds=1.0,
            operator_thread_count=1,
        ),
        dataset_storage=dataset_storage,
        local_buffer_broker_event_channel_provider=buffer_broker.get_event_channel,
        local_buffer_io=buffer_broker,
        worker_target=fake_deployment_process_worker,
    )

    buffer_broker.start()
    supervisor.start()
    try:
        initial_status = supervisor.get_status(config)
        assert initial_status.process_state == "stopped"
        assert initial_status.desired_state == "stopped"

        started_status = supervisor.start_deployment(config)
        assert started_status.process_state == "running"
        assert started_status.desired_state == "running"
        assert started_status.process_id is not None

        initial_health = _wait_for_health(supervisor, config)
        assert initial_health.healthy_instance_count == 2
        assert initial_health.warmed_instance_count == 2
        assert initial_health.pinned_output_total_bytes == 1048576
        assert initial_health.keep_warm is not None
        assert initial_health.keep_warm.activated is True

        warmup_health = supervisor.warmup_deployment(config)
        assert warmup_health.healthy_instance_count == 2
        assert warmup_health.warmed_instance_count == 2
        assert warmup_health.pinned_output_total_bytes == 1048576
        assert all(item.warmed is True for item in warmup_health.instances)
        assert warmup_health.keep_warm is not None
        assert warmup_health.keep_warm.activated is True

        execution_1 = supervisor.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_uri="runtime-inputs/image-1.jpg",
                score_threshold=0.3,
                save_result_image=True,
                extra_options={},
            ),
        )
        execution_2 = supervisor.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_uri="runtime-inputs/image-2.jpg",
                score_threshold=0.3,
                save_result_image=True,
                extra_options={},
            ),
        )
        assert execution_1.instance_id != execution_2.instance_id
        assert execution_1.execution_result.preview_image_bytes == b"preview-jpg"
        assert (
            execution_1.execution_result.runtime_session_info.metadata[
                "input_transport_kind"
            ]
            == "buffer"
        )
        batch_execution = supervisor.run_inference_batch(
            config=config,
            requests=(
                DetectionPredictionRequest(
                    input_uri="runtime-inputs/image-1.jpg",
                    score_threshold=0.3,
                    save_result_image=False,
                    extra_options={},
                ),
                DetectionPredictionRequest(
                    input_uri="runtime-inputs/image-2.jpg",
                    score_threshold=0.3,
                    save_result_image=False,
                    extra_options={},
                ),
            ),
        )
        assert len(batch_execution.execution_results) == 2
        assert batch_execution.instance_id.endswith(":instance-0")
        assert all(
            item.runtime_session_info.metadata["input_transport_kind"] == "buffer"
            for item in batch_execution.execution_results
        )

        state = supervisor._deployments[config.deployment_instance_id]
        assert state.process is not None
        previous_process_id = state.process.pid
        state.restart_counter.value = JSON_SAFE_INTEGER_MAX
        state.restart_counter.rollover_count = 0
        state.process.terminate()
        state.process.join(timeout=1.0)

        restarted_status = _wait_for_running_restart(
            supervisor, config, previous_process_id
        )
        assert restarted_status.restart_count == 1
        assert restarted_status.restart_count_rollover_count == 1
        assert restarted_status.process_id is not None
        assert restarted_status.process_id != previous_process_id
        recovered_health = _wait_for_health(supervisor, config)
        assert recovered_health.healthy_instance_count == 2
        assert recovered_health.warmed_instance_count == 2

        reset_health = supervisor.reset_deployment(config)
        assert reset_health.warmed_instance_count == 0
        assert reset_health.pinned_output_total_bytes == 0

        stopped_status = supervisor.stop_deployment(config)
        assert stopped_status.process_state == "stopped"
        assert stopped_status.desired_state == "stopped"
        assert stopped_status.process_id is None

        with pytest.raises(InvalidRequestError):
            supervisor.run_inference(
                config=config,
                request=DetectionPredictionRequest(
                    input_uri="runtime-inputs/image-3.jpg",
                    score_threshold=0.3,
                    save_result_image=False,
                    extra_options={},
                ),
            )
    finally:
        supervisor.stop()
        buffer_broker.stop()


def test_sync_inference_rejects_immediately_while_instances_are_warming(
    tmp_path: Path,
) -> None:
    """同步调用不得排在 startup warmup 后面等待。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-slow-warmup",
        runtime_target=_build_runtime_target(runtime_artifact_path),
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2)
        ),
    )
    supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=BackendServiceDeploymentProcessSupervisorConfig(
            auto_restart=False,
            request_timeout_seconds=30.0,
            shutdown_timeout_seconds=1.0,
            operator_thread_count=1,
        ),
        worker_target=fake_deployment_process_worker,
    )
    supervisor.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            start_future = executor.submit(supervisor.start_deployment, config)
            deadline = monotonic() + 10.0
            while monotonic() < deadline:
                if supervisor.get_status(config).process_state == "starting":
                    break
                sleep(0.01)
            else:
                raise AssertionError("未观察到 deployment starting 状态")

            call_started_at = monotonic()
            with pytest.raises(InvalidRequestError, match="正在加载或预热"):
                supervisor.run_inference(
                    config=config,
                    request=DetectionPredictionRequest(
                        input_image_bytes=b"image",
                        score_threshold=0.3,
                        save_result_image=False,
                        extra_options={},
                    ),
                )
            assert monotonic() - call_started_at < 0.5
            assert start_future.result(timeout=10.0).process_state == "running"
    finally:
        supervisor.stop()


def test_async_deployment_process_uses_object_store_without_local_buffer(
    tmp_path: Path,
) -> None:
    """验证持久异步输入和结果图均由 worker 直接访问 ObjectStore。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    input_key = "runtime/transfers/async/request/input.bin"
    output_key = "runtime/transfers/async/request/preview.bin"
    dataset_storage.write_bytes(input_key, b"image")
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-async-object-store",
        runtime_target=_build_runtime_target(runtime_artifact_path),
    )
    supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(dataset_storage.root_dir),
        runtime_mode="async",
        settings=BackendServiceDeploymentProcessSupervisorConfig(
            auto_restart=False,
            request_timeout_seconds=30.0,
            shutdown_timeout_seconds=1.0,
            operator_thread_count=1,
        ),
        dataset_storage=dataset_storage,
        worker_target=fake_deployment_process_worker,
    )

    supervisor.start()
    try:
        supervisor.start_deployment(config)
        execution = supervisor.run_inference(
            config=config,
            request=DetectionPredictionRequest(
                input_uri=input_key,
                score_threshold=0.3,
                save_result_image=True,
                extra_options={},
            ),
            preview_output_object_key=output_key,
        )

        assert execution.execution_result.preview_image_bytes is None
        assert execution.preview_image_transfer == {
            "object_key": output_key,
            "size": len(b"preview-jpg"),
            "media_type": "image/jpeg",
        }
        assert dataset_storage.resolve(output_key).read_bytes() == b"preview-jpg"
        assert not (tmp_path / "buffers").exists()
    finally:
        supervisor.stop()


def test_deployment_process_supervisor_limits_running_processes_across_supervisors(
    tmp_path: Path,
) -> None:
    """验证运行中 deployment 子进程上限会跨 sync/async supervisor 生效。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    running_config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-running",
        runtime_target=_build_runtime_target(runtime_artifact_path),
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    blocked_config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-blocked",
        runtime_target=_build_runtime_target(runtime_artifact_path),
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    settings = BackendServiceDeploymentProcessSupervisorConfig(
        auto_restart=False,
        monitor_interval_seconds=0.05,
        request_timeout_seconds=30.0,
        shutdown_timeout_seconds=1.0,
        max_running_process_count=1,
        operator_thread_count=1,
    )
    sync_supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=settings,
        worker_target=fake_deployment_process_worker,
    )
    async_supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="async",
        settings=settings,
        worker_target=fake_deployment_process_worker,
    )

    sync_supervisor.start()
    async_supervisor.start()
    try:
        started_status = sync_supervisor.start_deployment(running_config)
        assert started_status.process_state == "running"

        with pytest.raises(InvalidRequestError, match="达到配置上限"):
            async_supervisor.start_deployment(blocked_config)

        blocked_status = async_supervisor.get_status(blocked_config)
        assert blocked_status.process_state == "stopped"
        assert blocked_status.desired_state == "stopped"
        assert blocked_status.last_error is not None
        assert "max_running_process_count=1" in blocked_status.last_error

        sync_supervisor.stop_deployment(running_config)
        resumed_status = async_supervisor.start_deployment(blocked_config)
        assert resumed_status.process_state == "running"
        assert resumed_status.last_error is None
    finally:
        sync_supervisor.stop()
        async_supervisor.stop()


def test_deployment_process_supervisor_applies_and_releases_cpu_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 CPU 线程在 worker 启动前按本 deployment 裁剪，并在停止后删除记录。"""

    monkeypatch.setattr(
        cpu_device_resource_manager,
        "read_cpu_hardware_summary",
        lambda: {
            "cpu_physical_core_count": 6,
            "cpu_logical_processor_count": 12,
        },
    )
    runtime_artifact_path = tmp_path / "runtime-artifact.xml"
    runtime_artifact_path.write_bytes(b"fake-openvino-artifact")
    runtime_target = replace(
        _build_runtime_target(runtime_artifact_path),
        runtime_backend="openvino",
        runtime_artifact_file_type="openvino.xml",
    )
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-cpu-allocation",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2),
            backend_options=OpenVinoCpuRuntimeOptions(
                inference_num_threads=4,
                num_streams=1,
            ),
        ),
    )
    manager = CpuDeviceResourceManager()
    supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=BackendServiceDeploymentProcessSupervisorConfig(
            auto_restart=False,
            request_timeout_seconds=30.0,
            shutdown_timeout_seconds=1.0,
            operator_thread_count=8,
        ),
        cpu_device_resource_manager=manager,
        worker_target=fake_deployment_process_worker,
    )

    supervisor.start()
    try:
        supervisor.start_deployment(config)
        health = _wait_for_health(supervisor, config)

        assert (
            health.requested_runtime_configuration["backend_options"][
                "inference_num_threads"
            ]
            == 4
        )
        allocated = health.effective_runtime_configuration[
            "allocated_runtime_configuration"
        ]
        assert allocated["backend_options"]["inference_num_threads"] == 3
        assert manager.snapshot()["configured_thread_capacity"] == 6

        supervisor.stop_deployment(config)
        assert manager.snapshot()["configured_thread_capacity"] == 0
    finally:
        supervisor.stop()


def test_sync_and_async_openvino_deployments_share_cpu_without_startup_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 sync/async 常驻配置总和超过核心数时仍可同时启动。"""

    monkeypatch.setattr(
        cpu_device_resource_manager,
        "read_cpu_hardware_summary",
        lambda: {
            "cpu_physical_core_count": 6,
            "cpu_logical_processor_count": 12,
        },
    )
    runtime_artifact_path = tmp_path / "shared-runtime-artifact.xml"
    runtime_artifact_path.write_bytes(b"fake-openvino-artifact")
    runtime_target = replace(
        _build_runtime_target(runtime_artifact_path),
        runtime_backend="openvino",
        runtime_artifact_file_type="openvino.xml",
    )
    configuration = DeploymentRuntimeConfiguration(
        execution=DeploymentExecutionPolicy(instance_count=2),
        backend_options=OpenVinoCpuRuntimeOptions(
            inference_num_threads=4,
            num_streams=1,
        ),
    )
    sync_config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-openvino-sync",
        runtime_target=runtime_target,
        runtime_configuration=configuration,
    )
    async_config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-openvino-async",
        runtime_target=runtime_target,
        runtime_configuration=configuration,
    )
    settings = BackendServiceDeploymentProcessSupervisorConfig(
        auto_restart=False,
        request_timeout_seconds=30.0,
        shutdown_timeout_seconds=1.0,
        max_running_process_count=4,
        operator_thread_count=8,
    )
    manager = CpuDeviceResourceManager()
    sync_supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=settings,
        cpu_device_resource_manager=manager,
        worker_target=fake_deployment_process_worker,
    )
    async_supervisor = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="async",
        settings=settings,
        cpu_device_resource_manager=manager,
        worker_target=fake_deployment_process_worker,
    )

    sync_supervisor.start()
    async_supervisor.start()
    try:
        assert sync_supervisor.start_deployment(sync_config).process_state == "running"
        assert (
            async_supervisor.start_deployment(async_config).process_state == "running"
        )

        sync_health = _wait_for_health(sync_supervisor, sync_config)
        async_health = _wait_for_health(async_supervisor, async_config)
        for health in (sync_health, async_health):
            allocated = health.effective_runtime_configuration[
                "allocated_runtime_configuration"
            ]
            assert allocated["backend_options"]["inference_num_threads"] == 3

        snapshot = manager.snapshot()
        assert snapshot["active_deployment_count"] == 2
        assert snapshot["configured_thread_capacity"] == 12
        assert snapshot["shared_thread_capacity"] == 6
        assert snapshot["oversubscribed"] is False
    finally:
        sync_supervisor.stop()
        async_supervisor.stop()


def test_deployment_holds_shared_gpu_reservation_until_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多个 deployment 可共享 GPU；全部停止前 training exclusive 必须被拒绝。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-onnx")
    target = replace(
        _build_runtime_target(runtime_artifact_path),
        runtime_backend="tensorrt",
        device_name="cuda:0",
    )
    lock_root = tmp_path / "device-leases"
    resolver = _StaticCudaResolver()
    settings = BackendServiceDeploymentProcessSupervisorConfig(
        auto_restart=False,
        monitor_interval_seconds=0.05,
        startup_timeout_seconds=30.0,
        shutdown_timeout_seconds=1.0,
        device_leases=DeviceLeaseProviderConfig(
            root_dir=str(lock_root),
            shared_acquire_timeout_seconds=0.0,
        ),
    )
    first = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=settings,
        device_lease_provider=DeviceLeaseProvider(
            root_dir=lock_root,
            resolver=resolver,
        ),
        worker_target=fake_deployment_process_worker,
    )
    second = DeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="async",
        settings=settings,
        device_lease_provider=DeviceLeaseProvider(
            root_dir=lock_root,
            resolver=resolver,
        ),
        worker_target=fake_deployment_process_worker,
    )
    exclusive_provider = DeviceLeaseProvider(root_dir=lock_root, resolver=resolver)
    first_config = DeploymentProcessConfig(
        deployment_instance_id="gpu-deployment-1",
        runtime_target=target,
    )
    second_config = DeploymentProcessConfig(
        deployment_instance_id="gpu-deployment-2",
        runtime_target=target,
    )
    monkeypatch.setattr(
        "backend.service.application.runtime.deployment.deployment_process_supervisor.validate_runtime_target_available",
        lambda _target: None,
    )
    first.start()
    second.start()
    try:
        with exclusive_provider.acquire_resource(
            resolver.resource,
            requested_device="cuda:0",
            mode=DeviceLeaseMode.EXCLUSIVE,
            purpose="training",
            owner_id="training-before-deployment",
            timeout_seconds=0.0,
        ):
            with pytest.raises(DeviceLeaseUnavailableError):
                first.start_deployment(first_config)

        assert first.start_deployment(first_config).process_state == "running"
        assert second.start_deployment(second_config).process_state == "running"
        first_health = _wait_for_health(first, first_config)
        lease = first_health.effective_runtime_configuration["device_lease"]
        assert lease["resource_key"] == resolver.resource.resource_key
        assert lease["mode"] == "shared"

        with pytest.raises(DeviceLeaseUnavailableError):
            exclusive_provider.acquire_resource(
                resolver.resource,
                requested_device="cuda:0",
                mode=DeviceLeaseMode.EXCLUSIVE,
                purpose="training",
                owner_id="training-before-stop",
                timeout_seconds=0.0,
            )
        first.stop_deployment(first_config)
        with pytest.raises(DeviceLeaseUnavailableError):
            exclusive_provider.acquire_resource(
                resolver.resource,
                requested_device="cuda:0",
                mode=DeviceLeaseMode.EXCLUSIVE,
                purpose="training",
                owner_id="training-one-deployment-left",
                timeout_seconds=0.0,
            )
        second.stop_deployment(second_config)
        with exclusive_provider.acquire_resource(
            resolver.resource,
            requested_device="cuda:0",
            mode=DeviceLeaseMode.EXCLUSIVE,
            purpose="training",
            owner_id="training-after-stop",
            timeout_seconds=0.0,
        ) as training_lease:
            assert training_lease.info.mode == "exclusive"
    finally:
        first.stop()
        second.stop()


def _build_runtime_target(runtime_artifact_path: Path) -> RuntimeTargetSnapshot:
    """构建测试使用的最小 runtime target。"""

    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-1",
        model_version_id="model-version-1",
        model_build_id=None,
        model_name="yolox-test",
        model_scale="nano",
        model_type="yolox",
        task_type="detection",
        source_kind="training_output",
        runtime_profile_id=None,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        input_size=(64, 64),
        labels=("bolt",),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri="projects/project-1/models/builds/build-1/runtime-artifact.onnx",
        runtime_artifact_path=runtime_artifact_path,
        runtime_artifact_file_type="yolox.onnx",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri="projects/project-1/models/checkpoints/best_ckpt.pth",
        checkpoint_path=runtime_artifact_path,
        labels_storage_uri="projects/project-1/models/labels.txt",
    )


def _wait_for_running_restart(
    supervisor: DeploymentProcessSupervisor,
    config: DeploymentProcessConfig,
    previous_process_id: int | None,
) -> object:
    """等待 supervisor 完成崩溃拉起。"""

    # Windows spawn 后还要完成全部实例 warmup；等待的是可接收推理状态，
    # 不是仅有 pid 的中间状态。
    deadline = monotonic() + 15.0
    while monotonic() < deadline:
        status = supervisor.get_status(config)
        if (
            status.process_state == "running"
            and status.process_id is not None
            and status.process_id != previous_process_id
        ):
            return status
        sleep(0.05)
    raise AssertionError("deployment supervisor 未在预期时间内完成自动拉起")


def _wait_for_health(
    supervisor: DeploymentProcessSupervisor,
    config: DeploymentProcessConfig,
    *,
    timeout_seconds: float = 35.0,
) -> object:
    """等待 deployment 子进程进入可响应 health 的状态。"""

    deadline = monotonic() + timeout_seconds
    last_error: Exception | None = None
    while monotonic() < deadline:
        try:
            return supervisor.get_health(config)
        except ServiceConfigurationError as error:
            last_error = error
            sleep(0.1)
    raise AssertionError("deployment 进程未在预期时间内返回 health") from last_error
