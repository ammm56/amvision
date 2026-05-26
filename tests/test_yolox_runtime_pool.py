"""YOLOX ONNXRuntime runtime pool 逻辑测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolox_inference_runtime_pool import (
    YoloXDeploymentRuntimePool,
    YoloXDeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionRequest,
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
    config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-runtime-pool-1",
        runtime_target=runtime_target,
        instance_count=1,
    )
    request = YoloXPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image-bytes",
    )
    fake_session = FakePredictionSession(
        execution_result=build_test_execution_result(runtime_target=runtime_target)
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
    assert execution.instance_id == "deployment-instance-runtime-pool-1:instance-0"
    assert execution.execution_result.runtime_session_info.backend_name == "onnxruntime"
    assert execution.execution_result.runtime_session_info.device_name == "cpu"
    assert execution.execution_result.runtime_session_info.metadata["runtime_execution_mode"] == (
        "onnxruntime:fp32:cpu"
    )
    assert execution.execution_result.runtime_session_info.metadata["compiled_runtime_precision"] == "fp32"


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
    config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-runtime-pool-failure-1",
        runtime_target=runtime_target,
        instance_count=1,
    )
    request = YoloXPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image-bytes",
    )

    pool = YoloXDeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=build_failing_model_runtime(error_message="onnxruntime predict failed"),
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
    assert health.instances[0].last_error == "onnxruntime predict failed"


def test_runtime_pool_keeps_instance_healthy_after_invalid_request_failure(
    tmp_path: Path,
) -> None:
    """验证用户输入类 InvalidRequestError 不会把 deployment 实例打成 unhealthy。"""

    class InvalidRequestPredictionSession:
        """在 predict 时抛出 InvalidRequestError 的 fake runtime session。"""

        def __init__(self) -> None:
            """初始化 invalid request fake session。"""

            self.requests: list[YoloXPredictionRequest] = []

        def predict(self, request: YoloXPredictionRequest):
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
    config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-runtime-pool-invalid-request-1",
        runtime_target=runtime_target,
        instance_count=3,
    )
    request = YoloXPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"broken-image-bytes",
    )
    invalid_session = InvalidRequestPredictionSession()
    load_requests: list[tuple[object, object, object, object]] = []
    pool = YoloXDeploymentRuntimePool(
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