"""YOLOX deployment 进程监督器行为测试。"""

from __future__ import annotations

import os
from pathlib import Path
from queue import Empty
from time import monotonic, sleep

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
    YoloXDeploymentProcessSupervisor,
)
from backend.service.application.runtime.yolox_predictor import YoloXPredictionRequest
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.settings import BackendServiceDeploymentProcessSupervisorConfig


def test_deployment_process_supervisor_supports_lifecycle_and_auto_restart(tmp_path: Path) -> None:
    """验证 deployment 进程监督器支持启动、推理、停止和崩溃自动拉起。"""

    runtime_artifact_path = tmp_path / "runtime-artifact.onnx"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    config = YoloXDeploymentProcessConfig(
        deployment_instance_id="deployment-instance-supervisor-1",
        runtime_target=_build_runtime_target(runtime_artifact_path),
        instance_count=2,
    )
    supervisor = YoloXDeploymentProcessSupervisor(
        dataset_storage_root_dir=str(tmp_path),
        runtime_mode="sync",
        settings=BackendServiceDeploymentProcessSupervisorConfig(
            auto_restart=True,
            monitor_interval_seconds=0.05,
            request_timeout_seconds=2.0,
            shutdown_timeout_seconds=1.0,
            operator_thread_count=1,
        ),
        worker_target=fake_yolox_deployment_process_worker,
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

        initial_health = supervisor.get_health(config)
        assert initial_health.healthy_instance_count == 2
        assert initial_health.warmed_instance_count == 0

        warmup_health = supervisor.warmup_deployment(config)
        assert warmup_health.healthy_instance_count == 2
        assert warmup_health.warmed_instance_count == 2
        assert all(item.warmed is True for item in warmup_health.instances)

        execution_1 = supervisor.run_inference(
            config=config,
            request=YoloXPredictionRequest(
                input_uri="runtime-inputs/image-1.jpg",
                score_threshold=0.3,
                save_result_image=True,
                extra_options={},
            ),
        )
        execution_2 = supervisor.run_inference(
            config=config,
            request=YoloXPredictionRequest(
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
        state.process.terminate()
        state.process.join(timeout=1.0)

        restarted_status = _wait_for_running_restart(supervisor, config, previous_process_id)
        assert restarted_status.restart_count >= 1
        assert restarted_status.process_id is not None
        assert restarted_status.process_id != previous_process_id

        reset_health = supervisor.reset_deployment(config)
        assert reset_health.warmed_instance_count == 0

        stopped_status = supervisor.stop_deployment(config)
        assert stopped_status.process_state == "stopped"
        assert stopped_status.desired_state == "stopped"
        assert stopped_status.process_id is None

        with pytest.raises(InvalidRequestError):
            supervisor.run_inference(
                config=config,
                request=YoloXPredictionRequest(
                    input_uri="runtime-inputs/image-3.jpg",
                    score_threshold=0.3,
                    save_result_image=False,
                    extra_options={},
                ),
            )
    finally:
        supervisor.stop()


def fake_yolox_deployment_process_worker(
    *,
    config,
    dataset_storage_root_dir: str,
    request_queue,
    response_queue,
    operator_thread_count: int,
) -> None:
    """提供可预测响应的 fake deployment 子进程。"""

    del dataset_storage_root_dir
    del operator_thread_count

    warmed_instance_indexes: set[int] = set()
    next_instance_index = 0

    while True:
        try:
            message = request_queue.get(timeout=0.2)
        except Empty:
            continue

        request_id = str(message.get("request_id") or "")
        action = str(message.get("action") or "")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}

        if action == "shutdown":
            response_queue.put({"request_id": request_id, "ok": True, "payload": {}})
            return
        if action == "warmup":
            for instance_index in range(config.instance_count):
                warmed_instance_indexes.add(instance_index)
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(config=config, warmed_instance_indexes=warmed_instance_indexes),
                }
            )
            continue
        if action == "health":
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(config=config, warmed_instance_indexes=warmed_instance_indexes),
                }
            )
            continue
        if action == "reset":
            warmed_instance_indexes.clear()
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": _build_health_payload(config=config, warmed_instance_indexes=warmed_instance_indexes),
                }
            )
            continue
        if action == "infer":
            instance_index = next_instance_index % config.instance_count
            next_instance_index += 1
            warmed_instance_indexes.add(instance_index)
            response_queue.put(
                {
                    "request_id": request_id,
                    "ok": True,
                    "payload": {
                        "instance_id": f"{config.deployment_instance_id}:instance-{instance_index}",
                        "detections": [
                            {
                                "bbox_xyxy": [8.0, 10.0, 18.0, 22.0],
                                "score": 0.91,
                                "class_id": 0,
                                "class_name": "bolt",
                            }
                        ],
                        "latency_ms": 7.5,
                        "image_width": 64,
                        "image_height": 64,
                        "preview_image_bytes": b"preview-jpg" if payload.get("save_result_image") else None,
                        "runtime_session_info": {
                            "backend_name": config.runtime_target.runtime_backend,
                            "model_uri": config.runtime_target.runtime_artifact_storage_uri,
                            "device_name": config.runtime_target.device_name,
                            "input_spec": {"name": "images", "shape": [1, 3, 64, 64], "dtype": "float32"},
                            "output_spec": {"name": "detections", "shape": [-1, 7], "dtype": "float32"},
                            "metadata": {
                                "model_version_id": config.runtime_target.model_version_id,
                                "input_uri": payload.get("input_uri"),
                                "worker_pid": os.getpid(),
                            },
                        },
                    },
                }
            )
            continue

        response_queue.put(
            {
                "request_id": request_id,
                "ok": False,
                "error": {
                    "code": "invalid_request",
                    "message": "unsupported action",
                    "details": {"action": action},
                },
            }
        )


def _build_health_payload(
    *,
    config: YoloXDeploymentProcessConfig,
    warmed_instance_indexes: set[int],
) -> dict[str, object]:
    """构建 fake worker 返回的 health 负载。"""

    instances = []
    for instance_index in range(config.instance_count):
        instances.append(
            {
                "instance_id": f"{config.deployment_instance_id}:instance-{instance_index}",
                "healthy": True,
                "warmed": instance_index in warmed_instance_indexes,
                "busy": False,
                "last_error": None,
            }
        )
    return {
        "process_id": os.getpid(),
        "healthy_instance_count": config.instance_count,
        "warmed_instance_count": len(warmed_instance_indexes),
        "instances": instances,
    }


def _build_runtime_target(runtime_artifact_path: Path) -> RuntimeTargetSnapshot:
    """构建测试使用的最小 runtime target。"""

    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-1",
        model_version_id="model-version-1",
        model_build_id=None,
        model_name="yolox-test",
        model_scale="nano",
        task_type="detection",
        source_kind="training_output",
        runtime_profile_id=None,
        runtime_backend="onnxruntime",
        device_name="cpu",
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
    supervisor: YoloXDeploymentProcessSupervisor,
    config: YoloXDeploymentProcessConfig,
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