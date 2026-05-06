"""YOLOX TensorRT runtime pool 逻辑测试。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.runtime.yolox_inference_runtime_pool import (
    YoloXDeploymentRuntimePool,
    YoloXDeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionRequest,
)
from backend.service.domain.files.yolox_file_types import YOLOX_TENSORRT_ENGINE_FILE
from tests.runtime_pool_test_support import (
    FakePredictionSession,
    build_recording_model_runtime,
    build_test_execution_result,
    build_test_runtime_target,
    create_test_dataset_storage,
)


class _MemoryReportingPredictionSession(FakePredictionSession):
    """提供 pinned output buffer 占用快照的 fake prediction session。"""

    def __init__(
        self,
        *,
        execution_result,
        output_host_memory_kind: str,
        output_host_pinned_bytes: int,
    ) -> None:
        """初始化带 memory snapshot 的 fake session。"""

        super().__init__(execution_result=execution_result)
        self.output_host_memory_kind = output_host_memory_kind
        self.output_host_pinned_bytes = output_host_pinned_bytes

    def describe_memory_usage(self) -> dict[str, object]:
        """返回测试使用的输出 host buffer 占用快照。"""

        return {
            "output_host_memory_kind": self.output_host_memory_kind,
            "output_host_pinned_bytes": self.output_host_pinned_bytes,
        }


def test_runtime_pool_loads_tensorrt_session_once_and_reuses_warmed_instance(
    tmp_path: Path,
) -> None:
    """验证 runtime pool 会选择 TensorRT session，并在 warmup 后复用已加载实例。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="tensorrt",
        device_name="cuda:0",
        runtime_precision="fp16",
        runtime_artifact_file_name="fake-model.engine",
        runtime_artifact_file_type=YOLOX_TENSORRT_ENGINE_FILE,
    )
    config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-tensorrt-runtime-pool-1",
        runtime_target=runtime_target,
        instance_count=1,
    )
    request = YoloXPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image-bytes",
    )
    fake_session = FakePredictionSession(
        execution_result=build_test_execution_result(runtime_target=runtime_target, output_dtype="float16")
    )
    load_requests: list[tuple[object, object, object, object]] = []
    pool = YoloXDeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=build_recording_model_runtime(
            load_requests=load_requests,
            session=fake_session,
        ),
    )
    warmup_status = pool.warmup_deployment(config)
    execution = pool.run_inference(config=config, request=request)
    health = pool.get_health(config)

    assert len(load_requests) == 1
    assert load_requests[0] == (dataset_storage, runtime_target, None, None)
    assert warmup_status.healthy_instance_count == 1
    assert warmup_status.warmed_instance_count == 1
    assert health.healthy_instance_count == 1
    assert health.warmed_instance_count == 1
    assert health.instances[0].busy is False
    assert fake_session.requests == [request]
    assert execution.instance_id == "deployment-instance-tensorrt-runtime-pool-1:instance-0"
    assert execution.execution_result.runtime_session_info.backend_name == "tensorrt"
    assert execution.execution_result.runtime_session_info.device_name == "cuda:0"
    assert execution.execution_result.runtime_session_info.metadata["runtime_execution_mode"] == (
        "tensorrt:fp16:cuda:0"
    )
    assert execution.execution_result.runtime_session_info.metadata["compiled_runtime_precision"] == "fp16"


def test_runtime_pool_health_reports_total_pinned_output_bytes(
    tmp_path: Path,
) -> None:
    """验证 runtime pool health 会汇总所有已加载 session 的 pinned output 总量。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="tensorrt",
        device_name="cuda:0",
        runtime_precision="fp32",
        runtime_artifact_file_name="fake-model.engine",
        runtime_artifact_file_type=YOLOX_TENSORRT_ENGINE_FILE,
    )
    config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-tensorrt-runtime-pool-health-1",
        runtime_target=runtime_target,
        instance_count=2,
    )
    fake_session = _MemoryReportingPredictionSession(
        execution_result=build_test_execution_result(runtime_target=runtime_target, output_dtype="float32"),
        output_host_memory_kind="pinned",
        output_host_pinned_bytes=524288,
    )
    load_requests: list[tuple[object, object, object, object]] = []
    pool = YoloXDeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=build_recording_model_runtime(
            load_requests=load_requests,
            session=fake_session,
        ),
    )
    pool.warmup_deployment(config)
    health = pool.get_health(config)

    assert len(load_requests) == 2
    assert health.warmed_instance_count == 2
    assert health.pinned_output_total_bytes == 1048576
