"""deployment warmup 与 keep-warm 行为测试。"""

from __future__ import annotations

from pathlib import Path
from threading import Thread

from backend.service.application.deployments.yolox_deployment_service import (
    _resolve_process_runtime_behavior,
)
from backend.service.application.runtime.yolox_deployment_process_supervisor import (
    YoloXDeploymentProcessConfig,
    YoloXDeploymentProcessRuntimeBehavior,
)
from backend.service.application.runtime.safe_counter import (
    JSON_SAFE_INTEGER_MAX,
    SafeCounterState,
    increment_safe_counter,
)
from backend.service.application.runtime.yolox_deployment_process_worker import (
    _DeploymentWarmupBehavior,
    _KeepWarmState,
    _LocalBufferBrokerRuntimeHealth,
    _resolve_warmup_behavior,
    _run_dummy_warmup_passes,
    _run_keep_warm_loop,
    _snapshot_local_buffer_health,
    _snapshot_keep_warm_state,
)
from backend.service.application.runtime.yolox_inference_runtime_pool import (
    YoloXDeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.yolox_predictor import YoloXPredictionRequest
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.settings import BackendServiceDeploymentProcessSupervisorConfig


class _FakeRuntimePool:
    """提供最小计数能力的 fake runtime pool。"""

    def __init__(
        self,
        *,
        stop_state: _KeepWarmState | None = None,
        error_message: str | None = None,
    ) -> None:
        """初始化 fake runtime pool。

        参数：
        - stop_state：第一次执行后需要通知退出的 keep-warm 状态。
        - error_message：如果提供，则每次 fake 推理都会抛出这个错误。
        """

        self.stop_state = stop_state
        self.error_message = error_message
        self.call_count = 0
        self.requests: list[YoloXPredictionRequest] = []

    def run_inference(
        self,
        *,
        config: YoloXDeploymentRuntimePoolConfig,
        request: YoloXPredictionRequest,
    ) -> None:
        """记录一次 fake 推理调用。

        参数：
        - config：当前 deployment 的 runtime pool 配置。
        - request：本次推理请求。
        """

        del config
        self.call_count += 1
        self.requests.append(request)
        if self.stop_state is not None:
            self.stop_state.stop_event.set()
        if self.error_message is not None:
            raise RuntimeError(self.error_message)


def test_increment_safe_counter_normalizes_negative_value_and_rolls_over() -> None:
    """验证统一安全计数器会收敛负数，并在达到安全整数上限后 rollover。"""

    counter = SafeCounterState(value=-5, rollover_count=-3)

    assert counter.value == 0
    assert counter.rollover_count == 0

    counter.value = JSON_SAFE_INTEGER_MAX
    rolled_over = increment_safe_counter(counter)

    assert rolled_over is True
    assert counter.value == 1
    assert counter.rollover_count == 1


def test_resolve_process_runtime_behavior_reads_deployment_metadata_namespace() -> None:
    """验证 deployment_process metadata 可以解析 warmup 与 keep-warm 覆盖字段。"""

    behavior = _resolve_process_runtime_behavior(
        {
            "deployment_process": {
                "warmup_dummy_inference_count": 12,
                "warmup_dummy_image_size": [80, 48],
                "keep_warm_enabled": True,
                "keep_warm_interval_seconds": 0.2,
                "tensorrt_pinned_output_buffer_enabled": False,
                "tensorrt_pinned_output_buffer_max_bytes": 2097152,
            }
        }
    )

    assert behavior == YoloXDeploymentProcessRuntimeBehavior(
        warmup_dummy_inference_count=12,
        warmup_dummy_image_size=(80, 48),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.2,
        tensorrt_pinned_output_buffer_enabled=False,
        tensorrt_pinned_output_buffer_max_bytes=2097152,
    )


def test_resolve_warmup_behavior_merges_supervisor_defaults_and_deployment_overrides(tmp_path: Path) -> None:
    """验证 worker 会优先使用 deployment 覆盖值，并保留 supervisor 默认值。"""

    config = YoloXDeploymentProcessConfig(
        deployment_instance_id="deployment-instance-keep-warm-1",
        runtime_target=_build_runtime_target(tmp_path),
        instance_count=1,
        runtime_behavior=YoloXDeploymentProcessRuntimeBehavior(
            warmup_dummy_inference_count=9,
            keep_warm_enabled=True,
        ),
    )
    behavior = _resolve_warmup_behavior(
        config=config,
        supervisor_settings=BackendServiceDeploymentProcessSupervisorConfig(
            warmup_dummy_inference_count=6,
            warmup_dummy_image_size=(64, 64),
            keep_warm_enabled=False,
            keep_warm_interval_seconds=0.1,
            keep_warm_yield_timeout_seconds=0.7,
        ).model_dump(mode="python"),
    )

    assert behavior == _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=9,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.1,
        keep_warm_yield_timeout_seconds=0.7,
    )


def test_run_dummy_warmup_passes_executes_requested_count(tmp_path: Path) -> None:
    """验证真实 warmup 会按指定次数执行 dummy infer。"""

    runtime_pool = _FakeRuntimePool()
    runtime_pool_config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-warmup-1",
        runtime_target=_build_runtime_target(tmp_path),
        instance_count=1,
    )
    dummy_request = YoloXPredictionRequest(
        input_image_bytes=b"dummy-image-bytes",
        score_threshold=0.3,
        save_result_image=False,
        extra_options={"internal_request_kind": "test"},
    )

    _run_dummy_warmup_passes(
        runtime_pool=runtime_pool,
        runtime_pool_config=runtime_pool_config,
        dummy_request=dummy_request,
        count=3,
    )

    assert runtime_pool.call_count == 3
    assert runtime_pool.requests == [dummy_request, dummy_request, dummy_request]


def test_keep_warm_loop_runs_after_activation_and_stops_cleanly(tmp_path: Path) -> None:
    """验证 keep-warm 线程激活后会执行 dummy infer，并能及时退出。"""

    keep_warm_state = _KeepWarmState(
        dummy_request=YoloXPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        )
    )
    keep_warm_state.activated_event.set()
    runtime_pool = _FakeRuntimePool(stop_state=keep_warm_state)
    runtime_pool_config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-keep-warm-2",
        runtime_target=_build_runtime_target(tmp_path),
        instance_count=1,
    )
    behavior = _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=0,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.01,
        keep_warm_yield_timeout_seconds=0.2,
    )

    thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)

    assert runtime_pool.call_count == 1
    assert keep_warm_state.idle_event.is_set() is True
    assert keep_warm_state.success_counter.value == 1
    assert keep_warm_state.success_counter.rollover_count == 0
    assert keep_warm_state.error_counter.value == 0
    assert keep_warm_state.error_counter.rollover_count == 0
    assert thread.is_alive() is False


def test_keep_warm_loop_rolls_success_counter_and_exposes_rollover_count(tmp_path: Path) -> None:
    """验证 keep-warm 成功计数到达安全上限后会 rollover，并继续通过快照对外可观测。"""

    keep_warm_state = _KeepWarmState(
        dummy_request=YoloXPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        ),
        success_counter=SafeCounterState(value=JSON_SAFE_INTEGER_MAX),
    )
    keep_warm_state.activated_event.set()
    runtime_pool = _FakeRuntimePool(stop_state=keep_warm_state)
    runtime_pool_config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-keep-warm-rollover-1",
        runtime_target=_build_runtime_target(tmp_path),
        instance_count=1,
    )
    behavior = _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=0,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.01,
        keep_warm_yield_timeout_seconds=0.2,
    )

    thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)

    snapshot = _snapshot_keep_warm_state(
        behavior=behavior,
        keep_warm_state=keep_warm_state,
    )

    assert runtime_pool.call_count == 1
    assert snapshot["success_count"] == 1
    assert snapshot["success_count_rollover_count"] == 1
    assert snapshot["error_count"] == 0
    assert snapshot["error_count_rollover_count"] == 0


def test_snapshot_keep_warm_state_exposes_last_error(tmp_path: Path) -> None:
    """验证 keep-warm 状态快照会暴露最近一次失败错误。"""

    keep_warm_state = _KeepWarmState(
        dummy_request=YoloXPredictionRequest(
            input_image_bytes=b"dummy-image-bytes",
            score_threshold=0.3,
            save_result_image=False,
            extra_options={"internal_request_kind": "test"},
        ),
        error_counter=SafeCounterState(value=JSON_SAFE_INTEGER_MAX),
    )
    keep_warm_state.activated_event.set()
    runtime_pool = _FakeRuntimePool(
        stop_state=keep_warm_state,
        error_message="keep warm infer failed",
    )
    runtime_pool_config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-keep-warm-3",
        runtime_target=_build_runtime_target(tmp_path),
        instance_count=1,
    )
    behavior = _DeploymentWarmupBehavior(
        warmup_dummy_inference_count=0,
        warmup_dummy_image_size=(64, 64),
        keep_warm_enabled=True,
        keep_warm_interval_seconds=0.01,
        keep_warm_yield_timeout_seconds=0.2,
    )

    thread = Thread(
        target=_run_keep_warm_loop,
        kwargs={
            "runtime_pool": runtime_pool,
            "runtime_pool_config": runtime_pool_config,
            "keep_warm_state": keep_warm_state,
            "behavior": behavior,
        },
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)

    snapshot = _snapshot_keep_warm_state(
        behavior=behavior,
        keep_warm_state=keep_warm_state,
    )

    assert snapshot["enabled"] is True
    assert snapshot["activated"] is True
    assert snapshot["success_count"] == 0
    assert snapshot["success_count_rollover_count"] == 0
    assert snapshot["error_count"] == 1
    assert snapshot["error_count_rollover_count"] == 1
    assert snapshot["last_error"] == "keep warm infer failed"


def test_snapshot_local_buffer_health_exposes_input_counts_and_recent_error() -> None:
    """验证 deployment worker 会在 health 中暴露 broker 输入计数和最近错误。"""

    broker_health = _LocalBufferBrokerRuntimeHealth(
        connected=True,
        channel_id="broker-channel-1",
        buffer_input_count=2,
        frame_input_count=1,
        error_count=1,
        last_error="broker read failed",
    )

    snapshot = _snapshot_local_buffer_health(
        local_buffer_reader=None,
        local_buffer_health=broker_health,
    )

    assert snapshot["connected"] is True
    assert snapshot["channel_id"] == "broker-channel-1"
    assert snapshot["buffer_input_count"] == 2
    assert snapshot["frame_input_count"] == 1
    assert snapshot["error_count"] == 1
    assert snapshot["recent_error"] == "broker read failed"


def _build_runtime_target(tmp_path: Path) -> RuntimeTargetSnapshot:
    """构建测试使用的最小 runtime target。

    参数：
    - tmp_path：pytest 提供的临时目录。

    返回：
    - 可供 deployment process config 使用的最小 RuntimeTargetSnapshot。
    """

    runtime_artifact_path = tmp_path / "fake-runtime-artifact.engine"
    runtime_artifact_path.write_bytes(b"fake-runtime-artifact")
    return RuntimeTargetSnapshot(
        project_id="project-1",
        model_id="model-1",
        model_version_id="model-version-1",
        model_build_id="model-build-1",
        model_name="yolox-test",
        model_scale="nano",
        task_type="detection",
        source_kind="training_output",
        runtime_profile_id=None,
        runtime_backend="tensorrt",
        runtime_precision="fp16",
        device_name="cuda:0",
        input_size=(640, 640),
        labels=("bolt",),
        runtime_artifact_file_id="artifact-1",
        runtime_artifact_storage_uri=str(runtime_artifact_path),
        runtime_artifact_path=runtime_artifact_path,
        runtime_artifact_file_type="engine",
        checkpoint_file_id="checkpoint-1",
        checkpoint_storage_uri=str(runtime_artifact_path.with_suffix(".pth")),
        checkpoint_path=runtime_artifact_path,
        labels_storage_uri=str(runtime_artifact_path.with_suffix(".labels.txt")),
    )