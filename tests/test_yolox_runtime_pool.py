"""YOLOX ONNXRuntime runtime pool 逻辑测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.deployment.deployment_runtime_pool import (
    DeploymentRuntimePool,
    DeploymentRuntimePoolConfig,
    MAX_DEPLOYMENT_RUNTIME_BATCH_ITEMS,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionRequest,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentExecutionPolicy,
    DeploymentRuntimeConfiguration,
)
from backend.service.domain.files.yolox_file_types import YOLOX_ONNX_OPTIMIZED_FILE
from tests.runtime_pool_test_support import (
    FakePredictionSession,
    build_failing_model_runtime,
    build_recording_model_runtime,
    build_test_execution_result,
    build_test_runtime_target,
    create_test_dataset_storage,
)


def test_runtime_pool_loads_onnxruntime_session_once_and_reuses_warmed_instance(
    tmp_path: Path,
) -> None:
    """验证 runtime pool 会选择 ONNXRuntime session，并在 warmup 后复用已加载实例。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="fake-model.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-runtime-pool-1",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    request = DetectionPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image-bytes",
    )
    fake_session = FakePredictionSession(
        execution_result=build_test_execution_result(runtime_target=runtime_target)
    )
    load_requests: list[tuple[object, object, object]] = []
    pool = DeploymentRuntimePool(
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
    assert load_requests[0] == (
        dataset_storage,
        runtime_target,
        config.runtime_configuration,
    )
    assert warmup_status.healthy_instance_count == 1
    assert warmup_status.warmed_instance_count == 1
    assert health.healthy_instance_count == 1
    assert health.warmed_instance_count == 1
    assert health.instances[0].busy is False
    assert fake_session.requests == [request]
    assert execution.instance_id == "deployment-instance-runtime-pool-1:instance-0"
    assert execution.execution_result.runtime_session_info.backend_name == "onnxruntime"
    assert execution.execution_result.runtime_session_info.device_name == "cpu"
    assert execution.execution_result.runtime_session_info.metadata[
        "runtime_execution_mode"
    ] == ("onnxruntime:fp32:cpu")
    assert (
        execution.execution_result.runtime_session_info.metadata[
            "compiled_runtime_precision"
        ]
        == "fp32"
    )


def test_two_warmed_instances_complete_exact_two_concurrent_inferences(
    tmp_path: Path,
) -> None:
    """验证两实例 deployment 的每一轮两个同步节点调用都完整成功。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="two-instance-model.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-exact-two",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2)
        ),
    )
    request = DetectionPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image-bytes",
    )
    round_barrier = Barrier(2)
    session_lock = Lock()
    loaded_sessions: list[object] = []
    execution_result = build_test_execution_result(runtime_target=runtime_target)

    class _ConcurrentSession:
        """要求每轮两个 session 同时进入 predict 的测试会话。"""

        def predict(self, _request: DetectionPredictionRequest):
            round_barrier.wait(timeout=2.0)
            return execution_result

    def load_session(**_: object) -> object:
        session = _ConcurrentSession()
        with session_lock:
            loaded_sessions.append(session)
        return session

    pool = DeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=SimpleNamespace(load_session=load_session),
    )
    warmup = pool.warmup_deployment(config)
    observed_instance_pairs: list[set[str]] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        for _ in range(100):
            futures = tuple(
                executor.submit(pool.run_inference, config=config, request=request)
                for _ in range(2)
            )
            executions = tuple(future.result(timeout=3.0) for future in futures)
            observed_instance_pairs.append(
                {execution.instance_id for execution in executions}
            )

    assert warmup.warmed_instance_count == 2
    assert len(loaded_sessions) == 2
    assert all(
        pair
        == {
            "deployment-instance-exact-two:instance-0",
            "deployment-instance-exact-two:instance-1",
        }
        for pair in observed_instance_pairs
    )
    health = pool.get_health(config)
    assert all(not instance.busy for instance in health.instances)
    assert [instance.inference_count for instance in health.instances] == [100, 100]
    assert [instance.error_count for instance in health.instances] == [0, 0]


def test_runtime_pool_batch_reserves_one_instance_and_preserves_item_order(
    tmp_path: Path,
) -> None:
    """验证完整 Batch 只占用一个实例并按输入顺序返回结果。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="batch-model.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-batch-order",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2)
        ),
    )
    requests = tuple(
        DetectionPredictionRequest(
            score_threshold=float(index) / 10.0,
            save_result_image=False,
            input_image_bytes=f"image-{index}".encode(),
        )
        for index in range(4)
    )
    sessions: list[FakePredictionSession] = []

    def load_session(**_: object) -> FakePredictionSession:
        session = FakePredictionSession(
            execution_result=build_test_execution_result(runtime_target=runtime_target)
        )
        sessions.append(session)
        return session

    pool = DeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=SimpleNamespace(load_session=load_session),
    )
    pool.warmup_deployment(config)

    execution = pool.run_inference_batch(config=config, requests=requests)

    assert execution.instance_id == "deployment-instance-batch-order:instance-0"
    assert len(execution.execution_results) == len(requests)
    assert sessions[0].requests == list(requests)
    assert sessions[1].requests == []
    health = pool.get_health(config)
    assert [instance.inference_count for instance in health.instances] == [4, 0]
    assert all(not instance.busy for instance in health.instances)


def test_two_warmed_instances_complete_two_concurrent_batches(
    tmp_path: Path,
) -> None:
    """验证两实例部署可稳定完成两路并行 Batch，且批内不跨实例。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="two-batch-model.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-exact-two-batches",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2)
        ),
    )
    batch_size = 3
    requests = tuple(
        DetectionPredictionRequest(
            score_threshold=0.1,
            save_result_image=False,
            input_image_bytes=f"batch-image-{index}".encode(),
        )
        for index in range(batch_size)
    )
    item_barrier = Barrier(2)
    sessions: list[object] = []
    execution_result = build_test_execution_result(runtime_target=runtime_target)

    class _BatchSession:
        """要求两个实例在批内每个 item 上同步进入 predict。"""

        def __init__(self) -> None:
            self.requests: list[DetectionPredictionRequest] = []

        def predict(self, request: DetectionPredictionRequest):
            self.requests.append(request)
            item_barrier.wait(timeout=2.0)
            return execution_result

    def load_session(**_: object) -> object:
        session = _BatchSession()
        sessions.append(session)
        return session

    pool = DeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=SimpleNamespace(load_session=load_session),
    )
    pool.warmup_deployment(config)

    with ThreadPoolExecutor(max_workers=2) as executor:
        for _ in range(30):
            futures = tuple(
                executor.submit(
                    pool.run_inference_batch,
                    config=config,
                    requests=requests,
                )
                for _ in range(2)
            )
            executions = tuple(future.result(timeout=3.0) for future in futures)
            assert {execution.instance_id for execution in executions} == {
                "deployment-instance-exact-two-batches:instance-0",
                "deployment-instance-exact-two-batches:instance-1",
            }
            assert all(
                len(execution.execution_results) == batch_size
                for execution in executions
            )

    assert [len(session.requests) for session in sessions] == [90, 90]
    health = pool.get_health(config)
    assert [instance.inference_count for instance in health.instances] == [90, 90]
    assert [instance.error_count for instance in health.instances] == [0, 0]
    assert all(not instance.busy for instance in health.instances)


def test_runtime_pool_batch_rejects_empty_and_oversized_batches(
    tmp_path: Path,
) -> None:
    """验证 Batch 大小边界显式失败，不做隐藏拆分。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="batch-limits.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-batch-limits",
        runtime_target=runtime_target,
    )
    request = DetectionPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image",
    )
    pool = DeploymentRuntimePool(dataset_storage=dataset_storage)

    with pytest.raises(InvalidRequestError, match="至少需要 1 个请求"):
        pool.run_inference_batch(config=config, requests=())
    with pytest.raises(InvalidRequestError, match="请求数量超过上限") as caught:
        pool.run_inference_batch(
            config=config,
            requests=(request,) * (MAX_DEPLOYMENT_RUNTIME_BATCH_ITEMS + 1),
        )

    assert caught.value.details == {
        "count": MAX_DEPLOYMENT_RUNTIME_BATCH_ITEMS + 1,
        "max_count": MAX_DEPLOYMENT_RUNTIME_BATCH_ITEMS,
    }


def test_runtime_pool_batch_fails_fast_without_switching_to_second_instance(
    tmp_path: Path,
) -> None:
    """验证批内错误立即失败，绝不把剩余 item 切换到另一个健康实例。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="batch-fail-fast.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-batch-fail-fast",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2)
        ),
    )
    execution_result = build_test_execution_result(runtime_target=runtime_target)

    class _FailingSecondItemSession:
        def __init__(self, *, fail: bool) -> None:
            self.fail = fail
            self.requests: list[DetectionPredictionRequest] = []

        def predict(self, request: DetectionPredictionRequest):
            self.requests.append(request)
            if self.fail and len(self.requests) == 2:
                raise RuntimeError("second item failed")
            return execution_result

    sessions = (
        _FailingSecondItemSession(fail=True),
        _FailingSecondItemSession(fail=False),
    )
    next_session_index = 0

    def load_session(**_: object) -> object:
        nonlocal next_session_index
        session = sessions[next_session_index]
        next_session_index += 1
        return session

    requests = tuple(
        DetectionPredictionRequest(
            score_threshold=0.1,
            save_result_image=False,
            input_image_bytes=f"image-{item_index}".encode(),
        )
        for item_index in range(3)
    )
    pool = DeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=SimpleNamespace(load_session=load_session),
    )
    pool.warmup_deployment(config)

    with pytest.raises(
        ServiceConfigurationError,
        match="deployment 批量推理执行失败",
    ) as caught:
        pool.run_inference_batch(config=config, requests=requests)

    assert caught.value.details["item_index"] == 1
    assert sessions[0].requests == list(requests[:2])
    assert sessions[1].requests == []
    health = pool.get_health(config)
    assert health.instances[0].healthy is False
    assert health.instances[0].inference_count == 1
    assert health.instances[0].error_count == 1
    assert health.instances[1].healthy is True
    assert health.instances[1].inference_count == 0
    assert all(not instance.busy for instance in health.instances)


def test_runtime_pool_marks_onnxruntime_instance_unhealthy_after_predict_failure(
    tmp_path: Path,
) -> None:
    """验证 runtime pool 在 ONNXRuntime session predict 失败后会把实例标记为 unhealthy。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="fake-model.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-runtime-pool-failure-1",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(),
    )
    request = DetectionPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image-bytes",
    )

    pool = DeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=build_failing_model_runtime(
            error_message="onnxruntime predict failed"
        ),
    )

    with pytest.raises(ServiceConfigurationError) as caught_error:
        pool.run_inference(config=config, request=request)

    health = pool.get_health(config)

    assert str(caught_error.value) == "当前 deployment 没有可用的健康推理实例"
    assert health.healthy_instance_count == 0
    assert health.warmed_instance_count == 0
    assert health.instances[0].healthy is False
    assert health.instances[0].warmed is False
    assert health.instances[0].busy is False
    assert health.instances[0].inference_count == 0
    assert health.instances[0].error_count == 1
    assert health.instances[0].last_error == "onnxruntime predict failed"


def test_runtime_pool_warmup_preserves_session_load_errors(tmp_path: Path) -> None:
    """验证 session 加载失败会终止预热并返回实例级根因。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="fake-model.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-warmup-load-failure",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=2)
        ),
    )

    def load_session(**_: object) -> object:
        raise RuntimeError("OpenVINO NUM_STREAMS 配置无效")

    pool = DeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=SimpleNamespace(load_session=load_session),
    )

    with pytest.raises(
        ServiceConfigurationError,
        match="deployment 推理实例预热失败: OpenVINO NUM_STREAMS 配置无效",
    ) as caught_error:
        pool.warmup_deployment(config)

    assert caught_error.value.details["healthy_instance_count"] == 0
    assert caught_error.value.details["warmed_instance_count"] == 0
    assert caught_error.value.details["instances"] == [
        {
            "instance_id": "deployment-instance-warmup-load-failure:instance-0",
            "healthy": False,
            "warmed": False,
            "last_error": "OpenVINO NUM_STREAMS 配置无效",
        },
        {
            "instance_id": "deployment-instance-warmup-load-failure:instance-1",
            "healthy": False,
            "warmed": False,
            "last_error": "OpenVINO NUM_STREAMS 配置无效",
        },
    ]


def test_runtime_pool_keeps_instance_healthy_after_invalid_request_failure(
    tmp_path: Path,
) -> None:
    """验证用户输入类 InvalidRequestError 不会把 deployment 实例打成 unhealthy。"""

    class InvalidRequestPredictionSession:
        """在 predict 时抛出 InvalidRequestError 的 fake runtime session。"""

        def __init__(self) -> None:
            """初始化 invalid request fake session。"""

            self.requests: list[DetectionPredictionRequest] = []

        def predict(self, request: DetectionPredictionRequest):
            """记录请求并抛出用户输入错误。"""

            self.requests.append(request)
            raise InvalidRequestError(
                "input_image_bytes 不是可读取的图片内容",
                details={"field": "input_image_bytes"},
            )

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="onnxruntime",
        device_name="cpu",
        runtime_precision="fp32",
        runtime_artifact_file_name="fake-model.optimized.onnx",
        runtime_artifact_file_type=YOLOX_ONNX_OPTIMIZED_FILE,
    )
    config = DeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-runtime-pool-invalid-request-1",
        runtime_target=runtime_target,
        runtime_configuration=DeploymentRuntimeConfiguration(
            execution=DeploymentExecutionPolicy(instance_count=3)
        ),
    )
    request = DetectionPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"broken-image-bytes",
    )
    invalid_session = InvalidRequestPredictionSession()
    load_requests: list[tuple[object, object, object]] = []
    pool = DeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=build_recording_model_runtime(
            load_requests=load_requests,
            session=invalid_session,
        ),
    )

    with pytest.raises(InvalidRequestError) as caught_error:
        pool.run_inference(config=config, request=request)

    health = pool.get_health(config)

    assert caught_error.value.message == "input_image_bytes 不是可读取的图片内容"
    assert len(load_requests) == 1
    assert invalid_session.requests == [request]
    assert health.healthy_instance_count == 3
    assert health.warmed_instance_count == 1
    assert health.instances[0].healthy is True
    assert health.instances[0].warmed is True
    assert health.instances[0].busy is False
    assert health.instances[0].last_error is None
    assert health.instances[1].healthy is True
    assert health.instances[1].warmed is False
    assert health.instances[1].last_error is None
    assert health.instances[2].healthy is True
    assert health.instances[2].warmed is False
    assert health.instances[2].last_error is None
