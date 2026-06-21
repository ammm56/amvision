"""deployment 进程监督器行为测试。"""

from __future__ import annotations

from pathlib import Path
from time import monotonic, sleep

import pytest

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessConfig,
    DeploymentProcessSupervisor,
)
from backend.service.application.runtime.contracts.detection.prediction import DetectionPredictionRequest
from backend.service.application.runtime.support.safe_counter import JSON_SAFE_INTEGER_MAX
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.settings import BackendServiceDeploymentProcessSupervisorConfig
from tests.deployment_process_fake_worker import fake_deployment_process_worker


def test_deployment_process_supervisor_supports_lifecycle_and_auto_restart(tmp_path: Path) -> None:
    """验证 deployment 进程监督器支持启动、推理、停止和崩溃自动拉起。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    config = DeploymentProcessConfig(
        deployment_instance_id="deployment-instance-supervisor-1",
        runtime_target=_build_runtime_target(runtime_artifact_path),
        instance_count=2,
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
        worker_target=fake_deployment_process_worker,
    )

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
        assert initial_health.warmed_instance_count == 0
        assert initial_health.pinned_output_total_bytes == 0

        warmup_health = supervisor.warmup_deployment(config)
        assert warmup_health.healthy_instance_count == 2
        assert warmup_health.warmed_instance_count == 2
        assert warmup_health.pinned_output_total_bytes == 1048576
        assert all(item.warmed is True for item in warmup_health.instances)

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
        assert execution_1.execution_result.runtime_session_info.metadata["input_uri"] == "runtime-inputs/image-1.jpg"

        state = supervisor._deployments[config.deployment_instance_id]
        assert state.process is not None
        previous_process_id = state.process.pid
        state.restart_counter.value = JSON_SAFE_INTEGER_MAX
        state.restart_counter.rollover_count = 0
        state.process.terminate()
        state.process.join(timeout=1.0)

        restarted_status = _wait_for_running_restart(supervisor, config, previous_process_id)
        assert restarted_status.restart_count == 1
        assert restarted_status.restart_count_rollover_count == 1
        assert restarted_status.process_id is not None
        assert restarted_status.process_id != previous_process_id
        _wait_for_health(supervisor, config)

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

    deadline = monotonic() + 3.0
    while monotonic() < deadline:
        status = supervisor.get_status(config)
        if status.process_state == "running" and status.process_id is not None and status.process_id != previous_process_id:
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
